"""Main window that wires all widgets, workers and the core renamer."""
from __future__ import annotations

import csv
import logging
import os
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Slot, QUrl
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QWidget,
)

from ..core.config import ConfigManager
from ..core.coverage import CoverageReport, compute_coverage
from ..core.geojson_export import export_analysis_geojson
from ..core.models import PhotoItem
from ..core.rename_report import report_csv_path
from ..core.renamer_logic import RenamerLogic, photo_work_type_sort_key
from ..core.spatial_calculator import SpatialCalculator
from .help_tab import HelpTab
from .eliding_label import ElidingLabel
from .log_handler import QtLogHandler
from .log_tab import LogTab
from .map_tab import MapTab
from .preview_tab import PreviewTab
from .recents import push_recent
from .rename_outcome import backup_risk_note, classify_rename_outcome
from .sidebar import Sidebar
from . import theme as theme_module
from .session_store import SessionStore
from .undo_history import UndoHistory
from .video_dialog import VideoImportDialog
from .worker_controller import WorkerController
from .workers import (
    AnalysisWorker,
    AutoThresholdWorker,
    RenameWorker,
    UndoHistoryWorker,
    UndoWorker,
)

logger = logging.getLogger(__name__)


_METHOD_LABELS = {
    "empty": "sin datos (valor por defecto)",
    "single_sample": "una sola muestra",
    "degenerate": "muestras constantes",
    "small_sample": "muestra pequeña",
    "iqr_strict": "IQR estricto (Q3 + 1.5·IQR)",
    "iqr_relaxed": "IQR relajado (media con P90)",
}


class MainWindow(QMainWindow):
    """Application window with docked sidebar, central tabs and status bar."""

    def __init__(
        self,
        config_manager: ConfigManager,
        log_handler: QtLogHandler,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config_manager = config_manager
        self.log_handler = log_handler

        self.spatial_calc = SpatialCalculator()
        self.renamer = RenamerLogic(self.spatial_calc)
        self._sync_renamer_settings()
        self._worker_ctl = WorkerController(
            on_started=self._on_worker_started,
            on_cleared=self._on_worker_cleared,
        )
        self._loaded_kml_path = ""
        self._analysis_items: List[PhotoItem] = []
        #: Latest corridor coverage QA (set by ``_apply_preview``).
        self._coverage: Optional[CoverageReport] = None
        self._undo_history = UndoHistory()
        self._session_store = SessionStore()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._save_session)
        self._apply_autosave_timer()

        self._preview_debounce_timer = QTimer(self)
        self._preview_debounce_timer.setSingleShot(True)
        self._preview_debounce_timer.timeout.connect(self._debounced_refresh_preview)
        self._tray: Optional[QSystemTrayIcon] = None

        self.setWindowTitle("Renombrador PKS 2026")
        self.resize(1400, 900)
        self.setAcceptDrops(True)

        # Build UI
        self._build_sidebar()
        self._build_tabs()
        self._build_statusbar()
        self._build_menu()
        self._apply_stored_state()
        self._connect_signals()
        self._restore_last_session()
        self.sidebar.set_has_analysis(bool(self._analysis_items))
        self._update_workflow_banner()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_sidebar(self) -> None:
        self.sidebar = Sidebar(self.config_manager)
        dock = QDockWidget("Panel de control", self)
        dock.setObjectName("sidebarDock")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setWidget(self.sidebar)
        dock.setMinimumWidth(320)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)

    def _build_tabs(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(False)

        self.preview_tab = PreviewTab()
        self.map_tab = MapTab()
        self.log_tab = LogTab(self.log_handler)
        self.help_tab = HelpTab()

        self.tabs.addTab(self.preview_tab, "Vista previa")
        self.tabs.addTab(self.map_tab, "Mapa")
        self.tabs.addTab(self.log_tab, "Registro")
        self.tabs.addTab(self.help_tab, "Ayuda")
        self.setCentralWidget(self.tabs)

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        self.setStatusBar(bar)

        # Eliding: the coverage summary runs to ~300 characters and a plain
        # QLabel would make that the window's minimum width.
        self.status_message = ElidingLabel("Listo.")
        bar.addWidget(self.status_message, 1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(260)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        bar.addPermanentWidget(self.progress_bar)

        self.counter_label = QLabel("")
        self.counter_label.setProperty("role", "muted")
        bar.addPermanentWidget(self.counter_label)

    def _build_menu(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&Archivo")
        self._add_action(file_menu, "Seleccionar &carpeta…", "Ctrl+O",
                         lambda: self.sidebar.folder_selector._browse())
        self._add_action(file_menu, "Seleccionar &KML…", "Ctrl+K",
                         lambda: self.sidebar.kml_selector._browse())

        self.recent_folders_menu = file_menu.addMenu("Carpetas &recientes")
        self.recent_kmls_menu = file_menu.addMenu("KML r&ecientes")
        self._rebuild_recents_menus()

        file_menu.addSeparator()
        self._add_action(file_menu, "Importar &vídeo (SRT con GPS)…", "Ctrl+Shift+V",
                         self._on_import_video)
        self._add_action(file_menu, "&Exportar CSV", "Ctrl+E", self._export_csv)
        self._add_action(file_menu, "Exportar Geo&JSON…", "Ctrl+Shift+E", self._export_geojson)
        file_menu.addSeparator()
        self._add_action(file_menu, "&Salir", "Ctrl+Q", self.close)

        tools_menu = menubar.addMenu("&Herramientas")
        self._add_action(tools_menu, "&Analizar imágenes", "F5", self._on_analyze)
        self._add_action(tools_menu, "Actualizar &vista previa", "F6", self._on_refresh_preview)
        self._add_action(tools_menu, "&Procesar renombrado", "F7", self._on_process)
        self._add_action(tools_menu, "Generar &mapa", "F8", self._on_generate_map)
        tools_menu.addSeparator()
        self._add_action(tools_menu, "&Deshacer renombrado", None, self._on_undo)
        self._add_action(
            tools_menu,
            "&Historial de renombrados…",
            "Ctrl+H",
            self._on_undo_history,
        )
        self._add_action(tools_menu, "&Cancelar operación", "Esc", self._on_cancel)

        view_menu = menubar.addMenu("&Ver")
        self._add_action(view_menu, "Alternar &tema", "Ctrl+T", self._toggle_theme)

        help_menu = menubar.addMenu("Ay&uda")
        self._add_action(help_menu, "&Ayuda", "F1", lambda: self.tabs.setCurrentWidget(self.help_tab))

    def _add_action(self, menu, text: str, shortcut: Optional[str], handler) -> QAction:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _apply_stored_state(self) -> None:
        cfg = self.config_manager.config
        self.sidebar.set_values(
            folder=cfg.last_folder or "",
            kml_file=cfg.last_kml or "",
            threshold=cfg.threshold,
            suffix=cfg.last_suffix or "",
            create_backup=cfg.create_backup,
        )

    def _update_workflow_banner(self) -> None:
        if self._worker_ctl.busy:
            self.sidebar.set_workflow_hint(
                "<b>Operación en curso</b><br>"
                "Puedes cancelar con <b>Esc</b> si la barra de progreso está activa.",
                level="warning",
            )
            return
        if self._analysis_items:
            inside = sum(
                1
                for it in self._analysis_items
                if it.is_inside_threshold and not it.excluded and not it.virtual
            )
            thr = self.sidebar.get_config().threshold
            coverage_line, coverage_warns = self._coverage_hint()
            self.sidebar.set_workflow_hint(
                "<b>Listo para renombrar</b><br>"
                f"{len(self._analysis_items)} fotos · {inside} para renombrar · "
                f"umbral {thr:.1f} m<br>"
                f"{coverage_line}"
                "Revisa exclusiones o ajusta el umbral y pulsa <b>Procesar (F7)</b>.",
                level="warning" if coverage_warns else "success",
            )
            return

        folder_ok, kml_ok = self.sidebar.inputs_ready()
        if folder_ok and kml_ok:
            self.sidebar.set_workflow_hint(
                "<b>Listo para analizar</b><br>"
                "Carpeta y traza seleccionadas. Pulsa <b>Analizar (F5)</b> "
                "para calcular distancias y aplicar el umbral automático.",
                level="info",
            )
        elif folder_ok:
            self.sidebar.set_workflow_hint(
                "<b>Falta la traza</b><br>"
                "Selecciona el KML/KMZ/GeoJSON (o arrástralo a la ventana).",
                level="warning",
            )
        elif kml_ok:
            self.sidebar.set_workflow_hint(
                "<b>Falta la carpeta</b><br>"
                "Selecciona la carpeta de imágenes (o arrástrala a la ventana).",
                level="warning",
            )
        else:
            self.sidebar.set_workflow_hint(
                "<b>Empieza aquí</b><br>"
                "1. Carpeta de imágenes + traza KML<br>"
                "2. <b>Analizar</b> (F5) — aplica umbral automático<br>"
                "3. Revisa y <b>Renombra</b> (F7)",
                level="info",
            )

    def _coverage_hint(self) -> tuple[str, bool]:
        """Corridor QA line for the sidebar banner, plus "needs attention".

        Answers the question an operator can still act on while on site: is
        any stretch of the trace missing photos? Returns an HTML fragment
        (possibly empty) and whether it should raise the banner to warning.
        """
        cov = self._coverage
        if cov is None or cov.inside_count == 0:
            return "", False
        bits: List[str] = []
        if cov.coverage_ratio is not None:
            lo = SpatialCalculator.format_pk_label(cov.trace_start_pk_m or 0.0)
            hi = SpatialCalculator.format_pk_label(cov.trace_end_pk_m or 0.0)
            bits.append(
                f"Cobertura {cov.coverage_ratio * 100:.0f}% de la traza "
                f"(PK-{lo}–PK-{hi})"
            )
        interior = len(cov.interior_gaps)
        if interior:
            auto = " auto" if cov.gap_min_auto else ""
            bits.append(f"{interior} hueco(s) ≥{cov.gap_min_m:.0f} m{auto}")
        if cov.missing_pks:
            bits.append(f"{len(cov.missing_pks)}/{cov.pk_total} PK sin foto")
        if not bits:
            return "", False
        needs_attention = bool(interior or cov.missing_pks)
        return f"{' · '.join(bits)}<br>", needs_attention

    def _apply_threshold_value(self, value: float) -> None:
        """Set the sidebar threshold without re-entering the preview debounce loop."""
        spin = self.sidebar.threshold_spin
        spin.blockSignals(True)
        try:
            spin.setValue(float(value))
        finally:
            spin.blockSignals(False)

    def _sync_renamer_settings(self) -> None:
        """Apply persisted performance knobs to the core renamer."""
        cfg = self.config_manager.config
        self.renamer.max_workers = cfg.max_workers
        self.renamer.tukey_multiplier = cfg.iqr_multiplier
        self.renamer.set_viaduct_pks(cfg.viaduct_pks)

    def _apply_autosave_timer(self) -> None:
        """Start or stop periodic session snapshots based on config."""
        interval = int(self.config_manager.config.auto_save_interval)
        self._autosave_timer.stop()
        if interval > 0:
            self._autosave_timer.start(interval * 1000)

    def _persist_state(self) -> None:
        cfg = self.sidebar.get_config()
        try:
            # update_config already persists to disk; avoid a redundant rewrite.
            self.config_manager.update_config(
                last_folder=cfg.folder,
                last_kml=cfg.kml_file,
                last_suffix=cfg.suffix,
                threshold=cfg.threshold,
                create_backup=cfg.create_backup,
                theme=self.config_manager.config.theme,
            )
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to save config")

    def _apply_extra_landmarks(self) -> None:
        """Merge config landmarks into the UI-thread spatial calculator."""
        landmarks = self.config_manager.config.extra_landmarks
        if landmarks:
            self.spatial_calc.add_landmarks_from_dicts(landmarks)
        # Ficheros de landmarks del proyecto (Vertederos.kml y similares): el
        # cliente los edita entre entregas, asi que se leen en vez de copiar
        # coordenadas a mano en config.json.
        for kml_path in self.config_manager.config.landmark_kmls:
            try:
                self.spatial_calc.add_landmarks_from_kml(kml_path)
            except Exception:
                logger.warning("No se pudieron cargar landmarks de %s", kml_path)
        groups = self.config_manager.config.landmark_groups
        if groups:
            self.spatial_calc.set_landmark_groups(groups)
        radius = self.config_manager.config.landmark_capture_radius
        if radius > 0:
            self.spatial_calc.set_landmark_capture_radius(radius)
        cfg = self.config_manager.config
        self.spatial_calc.set_landmark_cluster_params(
            cluster_radius_m=cfg.landmark_cluster_radius,
            split_ratio=cfg.landmark_split_ratio,
        )

    def _connect_signals(self) -> None:
        self.sidebar.analyze_requested.connect(self._on_analyze)
        self.sidebar.preview_requested.connect(self._on_refresh_preview)
        self.sidebar.process_requested.connect(self._on_process)
        self.sidebar.cancel_requested.connect(self._on_cancel)
        self.sidebar.undo_requested.connect(self._on_undo)
        self.sidebar.export_csv_requested.connect(self._export_csv)
        self.sidebar.generate_map_requested.connect(self._on_generate_map)
        self.sidebar.auto_threshold_requested.connect(self._on_auto_threshold)
        self.sidebar.open_folder_requested.connect(self._open_folder)
        self.sidebar.threshold_spin.valueChanged.connect(self._on_preview_params_changed)
        self.sidebar.suffix_edit.textChanged.connect(self._on_preview_params_changed)
        self.sidebar.folder_selector.changed.connect(lambda _t: self._update_workflow_banner())
        self.sidebar.kml_selector.changed.connect(lambda _t: self._update_workflow_banner())
        self.preview_tab.show_on_map_requested.connect(self._show_photo_on_map)
        self.preview_tab.exclusion_changed.connect(self._on_preview_params_changed)

    def _apply_preview(self) -> bool:
        """Rebuild names, plan labels and histogram from ``_analysis_items``.

        Safe to call from worker finished handlers even while ``_worker_ctl``
        is still marked busy (clear runs after the finished slot).
        """
        items = self._analysis_items
        if not items:
            return False
        cfg = self.sidebar.get_config()
        self.renamer.build_preview_names(
            items,
            cfg.threshold,
            cfg.suffix,
            landmark_threshold=self.config_manager.config.landmark_threshold,
        )
        self.renamer.assign_destination_folders(items, cfg.folder or "")
        plan = self.renamer.build_preview_plan(items, cfg.folder or "")
        self.preview_tab.set_items(items)
        self.preview_tab.update_preview(items, plan=plan)
        inside = sum(
            1
            for it in items
            if it.is_inside_threshold and not it.excluded and not it.virtual
        )
        excluded = sum(1 for it in items if it.excluded)
        distances = [it.distance for it in items if it.distance != float("inf")]
        self.sidebar.set_histogram(distances, cfg.threshold)
        bits = [
            f"{inside} dentro del umbral ({cfg.threshold:.1f} m)",
            f"{len(items) - inside - excluded} fuera",
        ]
        if excluded:
            bits.append(f"{excluded} excluidas")
        # ``spatial_calc`` makes coverage trace-relative: head/tail holes and
        # PK placemarks with no photo, not just holes between photos.
        coverage = compute_coverage(items, spatial_calc=self.spatial_calc)
        self._coverage = coverage
        if coverage.inside_count > 0:
            bits.append(coverage.status_line())
        self.status_message.setText(" · ".join(bits))
        self._update_workflow_banner()
        if coverage.gap_count:
            logger.warning("Cobertura: %s", coverage.status_line(max_gaps=5))
        elif coverage.inside_count > 0:
            logger.info("Cobertura: %s", coverage.status_line())
        if coverage.missing_pks:
            shown = ", ".join(m.label for m in coverage.missing_pks[:10])
            more = len(coverage.missing_pks) - 10
            logger.warning(
                "PK sin foto (±%.0f m): %d de %d — %s%s",
                coverage.pk_tolerance_m,
                len(coverage.missing_pks),
                coverage.pk_total,
                shown,
                f" (+{more} más)" if more > 0 else "",
            )
        return True

    @Slot()
    def _on_preview_params_changed(self, *_args) -> None:
        """Debounce preview refresh when the user tweaks threshold or suffix."""
        if not self._analysis_items or self._worker_ctl.busy:
            return
        if not self.config_manager.config.auto_refresh_preview:
            return
        self._preview_debounce_timer.start(400)

    @Slot()
    def _debounced_refresh_preview(self) -> None:
        if not self._analysis_items:
            return
        self._persist_state()
        self._on_refresh_preview()

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------
    @Slot()
    def _on_analyze(self) -> None:
        if self._worker_ctl.busy:
            return
        cfg = self.sidebar.get_config()
        if not cfg.folder or not os.path.isdir(cfg.folder):
            self._error("Selecciona una carpeta de imágenes válida.")
            return
        if not cfg.kml_file or not os.path.isfile(cfg.kml_file):
            self._error("Selecciona un archivo KML/KMZ/GeoJSON válido antes de analizar.")
            return

        self._persist_state()
        self._push_recent("recent_folders", cfg.folder)
        if cfg.kml_file:
            self._push_recent("recent_kmls", cfg.kml_file)

        # Create June-style folders immediately (even if empty).
        try:
            self._apply_extra_landmarks()
            self.renamer.set_viaduct_pks(self.config_manager.config.viaduct_pks)
            self.renamer.ensure_work_folders(cfg.folder)
        except OSError as exc:
            logger.warning("No se pudieron crear carpetas de trabajo en %s: %s", cfg.folder, exc)

        worker = AnalysisWorker(
            cfg.folder,
            cfg.kml_file,
            max_workers=self.renamer.max_workers,
            tukey_multiplier=self.config_manager.config.iqr_multiplier,
            extra_landmarks=self.config_manager.config.extra_landmarks,
            landmark_kmls=self.config_manager.config.landmark_kmls,
            landmark_groups=self.config_manager.config.landmark_groups,
            landmark_capture_radius=self.config_manager.config.landmark_capture_radius,
            landmark_cluster_radius=self.config_manager.config.landmark_cluster_radius,
            landmark_split_ratio=self.config_manager.config.landmark_split_ratio,
            viaduct_pks=self.config_manager.config.viaduct_pks,
        )
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_analysis_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker_ctl.start(worker, "Analizando imágenes…")

    @Slot()
    def _on_refresh_preview(self) -> None:
        if self._worker_ctl.busy:
            return
        if not self._analysis_items:
            self._error("Primero ejecuta un análisis (F5).")
            return
        self._apply_preview()

    @Slot()
    def _on_process(self) -> None:
        if self._worker_ctl.busy:
            self._error(
                "Hay otra operación en curso.\n\n"
                "Espera a que termine o pulsa Esc para cancelar antes de renombrar."
            )
            return
        if not self._analysis_items:
            self._error("Primero ejecuta un análisis (F5).")
            return

        cfg = self.sidebar.get_config()
        self._persist_state()
        self._sync_renamer_settings()
        # Recompute preview flags so F7 honours the current threshold/suffix
        # even when the user skipped F6 after tweaking the sidebar.
        self.renamer.build_preview_names(
            self._analysis_items,
            cfg.threshold,
            cfg.suffix,
            landmark_threshold=self.config_manager.config.landmark_threshold,
        )

        items = [it for it in self._analysis_items if it.is_inside_threshold and not it.excluded]
        if not items:
            self._error("No hay fotos marcadas para renombrar. Incluye al menos una.")
            return

        plan = self.renamer.get_rename_plan(self._analysis_items, cfg.folder)
        dup_included = sum(1 for it in items if it.duplicate_of)
        conflict_bits = []
        if plan.get("photo_conflicts"):
            conflict_bits.append(f"{plan['photo_conflicts']} foto")
        if plan.get("sidecar_conflicts"):
            conflict_bits.append(f"{plan['sidecar_conflicts']} sidecar")
        conflict_detail = (
            f" ({', '.join(conflict_bits)})" if conflict_bits else ""
        )

        if plan["conflicts"] > 0 and plan["effective"] == 0:
            self._error(
                f"Hay {plan['conflicts']} conflictos de nombre{conflict_detail} "
                "y ningún archivo se puede renombrar de forma segura.\n\n"
                "Ajusta la plantilla, el umbral o excluye fotos duplicadas."
            )
            return

        dup_note = ""
        if dup_included:
            dup_note = (
                f"\nIncluye {dup_included} duplicada(s) detectada(s). "
                "Usa «Excluir duplicadas» en Vista previa si quieres omitirlas.\n"
            )
        risk_note = backup_risk_note(
            folder=cfg.folder, create_backup=cfg.create_backup
        )

        if plan["conflicts"] > 0:
            ok = QMessageBox.warning(
                self,
                "Conflictos de nombre",
                (
                    f"Se detectaron {plan['conflicts']} conflictos{conflict_detail}: "
                    f"esos archivos se omitirán.\n"
                    f"Se renombrarán {plan['effective']} de {plan['total']} "
                    f"archivos planificados.\n"
                    f"Sin cambios: {plan['unchanged']}"
                    f"{dup_note}{risk_note}\n"
                    "¿Continuar omitiendo los conflictos?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
        else:
            ok = QMessageBox.question(
                self,
                "Confirmar renombrado",
                (
                    f"Se van a procesar {plan['total']} archivos.\n"
                    f"Sin cambios: {plan['unchanged']}"
                    f"{dup_note}{risk_note}\n"
                    "¿Deseas continuar?"
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
        if ok != QMessageBox.Yes:
            return

        logger.info(
            "Iniciando renombrado: %s archivos en %s (backup=%s)",
            plan["effective"],
            cfg.folder,
            cfg.create_backup,
        )
        # Dedicated core instance so F7 never mutates the UI-thread renamer
        # while PhotoItems are being rewritten on disk.
        self._sync_renamer_settings()
        rename_core = RenamerLogic(
            self.spatial_calc,
            max_workers=self.renamer.max_workers,
            tukey_multiplier=self.renamer.tukey_multiplier,
        )
        rename_core.set_viaduct_pks(list(self.config_manager.config.viaduct_pks))
        worker = RenameWorker(
            self._analysis_items, cfg.folder, cfg.create_backup, rename_core
        )
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_rename_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker_ctl.start(worker, "Renombrando archivos…")

    @Slot()
    def _on_undo(self) -> None:
        if self._worker_ctl.busy:
            return
        cfg = self.sidebar.get_config()
        if not cfg.folder or not os.path.isdir(cfg.folder):
            self._error("Selecciona una carpeta válida para deshacer.")
            return

        entry = self._undo_history.latest_for_folder(cfg.folder)
        if entry is not None:
            ok = QMessageBox.question(
                self,
                "Confirmar deshacer",
                (
                    f"¿Revertir el renombrado del {entry.timestamp_str}?\n"
                    f"Fotos registradas: {entry.total}\n\n"
                    "Se restaurarán los nombres originales dentro de la carpeta."
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if ok != QMessageBox.Yes:
                return
            worker = UndoHistoryWorker(entry)
            worker.finished.connect(self._on_undo_history_finished)
            worker.failed.connect(self._on_worker_failed)
            self._worker_ctl.start(worker, "Revertiendo renombrado…")
            return

        if not report_csv_path(cfg.folder).is_file():
            self._error(
                "No hay renombrados registrados para esta carpeta.\n\n"
                "Usa «Historial de renombrados…» (Ctrl+H) si trabajaste en otra ruta, "
                "o renombra primero para generar el informe CSV."
            )
            return

        ok = QMessageBox.question(
            self,
            "Confirmar deshacer",
            "¿Revertir usando reporte_renombrado.csv?\n"
            "(No hay entrada en el historial interno para esta carpeta.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return

        worker = UndoWorker(cfg.folder, self.renamer)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_undo_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker_ctl.start(worker, "Revertiendo renombrado…")

    @Slot()
    def _on_cancel(self) -> None:
        if not self._worker_ctl.cancel():
            return
        self.status_message.setText("Cancelando…")

    @Slot()
    def _on_auto_threshold(self) -> None:
        if self._worker_ctl.busy:
            return
        if not self._analysis_items:
            self._error("Primero ejecuta un análisis (F5).")
            return
        cfg = self.config_manager.config
        worker = AutoThresholdWorker(
            list(self._analysis_items),
            tukey_multiplier=cfg.iqr_multiplier,
        )
        worker.finished.connect(self._on_auto_threshold_finished)
        worker.failed.connect(self._on_worker_failed)
        self._worker_ctl.start(worker, "Calculando umbral automático…")

    @Slot()
    def _on_generate_map(self) -> None:
        if not self._analysis_items:
            self._error("Primero ejecuta un análisis (F5).")
            return
        cfg = self.sidebar.get_config()
        points = [
            {
                "path": it.path,
                "name": it.name,
                "lat": it.lat,
                "lon": it.lon,
                "distance": it.distance,
                "pk": it.pk_value,
                "nearest_name": it.nearest_name,
                "gimbal_yaw": it.gimbal_yaw,
                "flight_yaw": it.flight_yaw,
                "rel_altitude": it.rel_altitude,
                "view_label": it.view_label,
                "date_str": it.date_str,
                "time_str": it.time_str,
            }
            for it in self._analysis_items
        ]
        kml_coords: List[list] = []
        if self.spatial_calc.project_axis is not None:
            kml_coords = [[lat, lon] for lon, lat in self.spatial_calc.project_axis.coords]
        kml_points = [
            {"name": pt.name, "lat": pt.lat, "lon": pt.lon}
            for pt in self.spatial_calc.named_points
        ]
        self.map_tab.render_points(points, kml_coords, kml_points, cfg.threshold)
        self.tabs.setCurrentWidget(self.map_tab)

    @Slot(object)
    def _show_photo_on_map(self, item: PhotoItem) -> None:
        if not item or not self._analysis_items:
            return
        self._on_generate_map()
        self.map_tab.focus_photo(item.name)

    @Slot()
    def _export_csv(self) -> None:
        if not self._analysis_items:
            self._error("No hay datos que exportar. Ejecuta un análisis primero.")
            return
        default_name = "analisis_imagenes.csv"
        cfg = self.sidebar.get_config()
        start_dir = cfg.folder or os.getcwd()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar CSV",
            os.path.join(start_dir, default_name),
            "CSV (*.csv);;Todos los archivos (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "original", "lat", "lon", "altitud_rel_m", "fecha", "hora",
                    "distancia_m", "pk_mas_cercano", "pk_valor", "pk_cadena", "vista",
                    "dentro_umbral", "destino", "nuevo_nombre", "duplicada_de",
                ])
                for it in self._analysis_items:
                    writer.writerow([
                        it.name,
                        f"{it.lat:.6f}",
                        f"{it.lon:.6f}",
                        f"{it.rel_altitude:.1f}" if it.rel_altitude is not None else "",
                        it.date_str,
                        it.time_str,
                        f"{it.distance:.3f}" if it.distance != float("inf") else "",
                        it.nearest_name or "",
                        f"{it.pk_value:.3f}",
                        SpatialCalculator.format_pk_label(it.pk_value),
                        it.view_label or "",
                        "si" if it.is_inside_threshold else "no",
                        it.dest_rel or ("(raíz)" if it.is_inside_threshold and it.new_name_base else ""),
                        it.new_name_base,
                        it.duplicate_of or "",
                    ])
                coverage = compute_coverage(
                    self._analysis_items, spatial_calc=self.spatial_calc
                )
                if coverage.coverage_ratio is not None:
                    writer.writerow([])
                    writer.writerow(["resumen_cobertura", "valor"])
                    writer.writerow([
                        "traza_pk_inicio",
                        SpatialCalculator.format_pk_label(coverage.trace_start_pk_m or 0.0),
                    ])
                    writer.writerow([
                        "traza_pk_fin",
                        SpatialCalculator.format_pk_label(coverage.trace_end_pk_m or 0.0),
                    ])
                    writer.writerow(["traza_longitud_m", f"{coverage.trace_length_m:.1f}"])
                    writer.writerow(["cubierto_m", f"{coverage.covered_m:.1f}"])
                    writer.writerow(
                        ["cobertura_pct", f"{coverage.coverage_ratio * 100:.1f}"]
                    )
                    if coverage.pk_total:
                        writer.writerow([
                            "pk_con_foto",
                            f"{coverage.covered_pk_count}/{coverage.pk_total}",
                        ])
                if coverage.gaps:
                    writer.writerow([])
                    writer.writerow(
                        ["hueco_inicio_pk", "hueco_fin_pk", "longitud_m", "tipo"]
                    )
                    for gap in coverage.gaps:
                        writer.writerow([
                            SpatialCalculator.format_pk_label(gap.start_pk_m),
                            SpatialCalculator.format_pk_label(gap.end_pk_m),
                            f"{gap.length_m:.1f}",
                            gap.kind,
                        ])
                if coverage.missing_pks:
                    writer.writerow([])
                    writer.writerow(["pk_sin_foto", "pk_valor_m", "tolerancia_m"])
                    for missing in coverage.missing_pks:
                        writer.writerow([
                            missing.name,
                            f"{missing.pk_m:.1f}",
                            f"{coverage.pk_tolerance_m:.0f}",
                        ])
            self._info(f"CSV exportado a:\n{path}")
        except OSError as exc:
            self._error(f"No se pudo escribir el CSV: {exc}")

    @Slot()
    def _export_geojson(self) -> None:
        if not self._analysis_items:
            self._error("No hay datos que exportar. Ejecuta un análisis primero.")
            return
        cfg = self.sidebar.get_config()
        start_dir = cfg.folder or os.getcwd()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar GeoJSON",
            os.path.join(start_dir, "analisis_pks.geojson"),
            "GeoJSON (*.geojson *.json);;Todos los archivos (*.*)",
        )
        if not path:
            return
        try:
            coverage = export_analysis_geojson(
                self._analysis_items, path, spatial_calc=self.spatial_calc
            )
            bits = [f"GeoJSON exportado a:\n{path}", coverage.status_line()]
            self._info("\n\n".join(bits))
        except OSError as exc:
            self._error(f"No se pudo escribir el GeoJSON: {exc}")
        except Exception as exc:
            logger.exception("Error exportando GeoJSON")
            self._error(f"Error exportando GeoJSON: {exc}")


    @Slot()
    def _toggle_theme(self) -> None:
        current = self.config_manager.config.theme
        new_theme = theme_module.toggle(current)
        self.config_manager.update_config(theme=new_theme)
        self.config_manager.save_config()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(theme_module.get_stylesheet(new_theme))
        labels = {"dark": "oscuro", "light": "claro", "system": "seguir al sistema"}
        self.status_message.setText(f"Tema: {labels.get(new_theme, new_theme)}")
        for widget in (self.counter_label, self.preview_tab.count_label):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _open_folder(self) -> None:
        cfg = self.sidebar.get_config()
        if not cfg.folder or not os.path.isdir(cfg.folder):
            return
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(cfg.folder))

    # ------------------------------------------------------------------
    # Drag & drop
    # ------------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if os.path.isdir(local):
                self.sidebar.set_values(folder=local)
                self.status_message.setText(f"Carpeta arrastrada: {local}")
                self._persist_state()
                break
            if os.path.isfile(local) and local.lower().endswith(
                (".kml", ".kmz", ".geojson", ".json")
            ):
                self.sidebar.set_values(kml_file=local)
                self.status_message.setText(f"KML arrastrado: {local}")
                self._persist_state()
                break
        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Recents
    # ------------------------------------------------------------------
    def _rebuild_recents_menus(self) -> None:
        cfg = self.config_manager.config

        self.recent_folders_menu.clear()
        for path in cfg.recent_folders or []:
            act = self.recent_folders_menu.addAction(path)
            act.triggered.connect(lambda _checked=False, p=path: self._load_recent_folder(p))
        if not cfg.recent_folders:
            empty = self.recent_folders_menu.addAction("(sin entradas recientes)")
            empty.setEnabled(False)

        self.recent_kmls_menu.clear()
        for path in cfg.recent_kmls or []:
            act = self.recent_kmls_menu.addAction(path)
            act.triggered.connect(lambda _checked=False, p=path: self._load_recent_kml(p))
        if not cfg.recent_kmls:
            empty = self.recent_kmls_menu.addAction("(sin entradas recientes)")
            empty.setEnabled(False)

    def _load_recent_folder(self, path: str) -> None:
        if not os.path.isdir(path):
            self._error(f"La carpeta ya no existe:\n{path}")
            return
        self.sidebar.set_values(folder=path)

    def _load_recent_kml(self, path: str) -> None:
        if not os.path.isfile(path):
            self._error(f"El archivo ya no existe:\n{path}")
            return
        self.sidebar.set_values(kml_file=path)

    def _push_recent(self, key: str, value: str) -> None:
        if not value:
            return
        cfg = self.config_manager.config
        current: List[str] = list(getattr(cfg, key, []) or [])
        updated = push_recent(current, value, cfg.MAX_RECENTS)
        self.config_manager.update_config(**{key: updated})
        self._rebuild_recents_menus()

    # ------------------------------------------------------------------
    # Video import
    # ------------------------------------------------------------------
    def _on_import_video(self) -> None:
        dialog = VideoImportDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        items = dialog.result_items()
        if not items:
            return
        # Cross SRT frames with the loaded KML so preview / rename see real
        # PK distance instead of the PhotoItem defaults (inf / 0).
        self.renamer.enrich_items_spatial(items)
        self._analysis_items.extend(items)
        self._analysis_items.sort(key=photo_work_type_sort_key)
        self._on_refresh_preview()
        self.status_message.setText(
            f"Importados {len(items)} puntos desde SRT (solo análisis y cobertura; "
            f"no se renombran). Total: {len(self._analysis_items)}."
        )

    # ------------------------------------------------------------------
    # Undo history
    # ------------------------------------------------------------------
    def _on_undo_history(self) -> None:
        if self._worker_ctl.busy:
            self._error(
                "Espera a que termine la operación en curso antes de abrir el historial."
            )
            return
        from .undo_dialog import UndoHistoryDialog
        dialog = UndoHistoryDialog(self._undo_history, self)
        dialog.exec()

    # ------------------------------------------------------------------
    # Autosave / restore
    # ------------------------------------------------------------------
    def _save_session(self) -> None:
        cfg = self.sidebar.get_config()
        self._session_store.save(cfg.folder, cfg.kml_file, self._analysis_items)

    def _restore_last_session(self) -> None:
        session = self._session_store.load()
        if not session:
            return

        folder = session["folder"]
        kml = session["kml"]
        if folder and os.path.isdir(folder):
            self.sidebar.set_values(folder=folder)
        if kml and os.path.isfile(kml):
            self.sidebar.set_values(kml_file=kml)
            try:
                self.spatial_calc.load_kml(kml)
                self._apply_extra_landmarks()
            except Exception:
                logger.warning("No se pudo recargar el KML de la sesión: %s", kml)

        existing: List[PhotoItem] = session["items"]
        self._analysis_items = existing
        self._analysis_items.sort(key=photo_work_type_sort_key)
        self.sidebar.set_has_analysis(True)
        self.preview_tab.set_items(self._analysis_items)

        restored_count = session["restored_count"]
        total_count = session["total_count"]
        # Rebuild names/histogram immediately so the operator doesn't need F6.
        try:
            self._apply_preview()
        except Exception:
            logger.exception("No se pudo refrescar la vista previa de la sesión restaurada")

        if restored_count == total_count:
            self.status_message.setText(
                f"Sesión anterior restaurada: {restored_count} fotos listas para revisar."
            )
        else:
            self.status_message.setText(
                f"Sesión restaurada parcialmente: {restored_count} de "
                f"{total_count} fotos siguen disponibles."
            )

    # ------------------------------------------------------------------
    # Tray notifications
    # ------------------------------------------------------------------
    def _notify(self, title: str, message: str) -> None:
        if not self.config_manager.config.notify_on_finish:
            return
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self._tray is None:
                self._tray = QSystemTrayIcon(self.windowIcon(), self)
                self._tray.setToolTip(title)
                self._tray.show()
            self._tray.showMessage(title, message, QSystemTrayIcon.Information, 5000)

    # ------------------------------------------------------------------
    # Worker plumbing
    # ------------------------------------------------------------------
    def _on_worker_started(self, message: str) -> None:
        # Pause autosave while PhotoItems / FS may be mutating in the worker.
        self._autosave_timer.stop()
        self.sidebar.set_busy(True)
        self._update_workflow_banner()
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 0)  # busy indicator until first progress
        self.status_message.setText(message)
        self.counter_label.setText("")

    def _on_worker_cleared(self) -> None:
        self.sidebar.set_busy(False)
        self.progress_bar.setRange(0, 100)
        self._apply_autosave_timer()
        self._update_workflow_banner()

    @Slot(int, int, str)
    def _on_progress(self, done: int, total: int, message: str) -> None:
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(done)
            self.counter_label.setText(f"{done}/{total}")
        else:
            self.progress_bar.setRange(0, 0)
        if message:
            self.status_message.setText(message)

    @Slot(object)
    def _on_analysis_finished(self, result) -> None:
        self.sidebar.set_busy(False)
        self.progress_bar.setRange(0, 100)
        if isinstance(result, dict) and result.get("cancelled"):
            self.status_message.setText("Análisis cancelado.")
            self.progress_bar.setValue(0)
            return
        items = result.get("items", []) if isinstance(result, dict) else []
        self._analysis_items = items
        suggested = result.get("suggested") if isinstance(result, dict) else None
        method = result.get("method", "empty") if isinstance(result, dict) else "empty"
        samples = int(result.get("samples", 0)) if isinstance(result, dict) else 0
        duplicates = int(result.get("duplicates", 0)) if isinstance(result, dict) else 0

        kml_path = result.get("kml_path") if isinstance(result, dict) else None
        if kml_path and os.path.isfile(kml_path):
            try:
                self.spatial_calc.load_kml(kml_path)
                self._apply_extra_landmarks()
                self._loaded_kml_path = kml_path
            except Exception:
                logger.warning("No se pudo sincronizar el KML tras el análisis: %s", kml_path)

        cfg = self.sidebar.get_config()
        if cfg.folder and os.path.isdir(cfg.folder):
            try:
                self.renamer.ensure_work_folders(cfg.folder)
            except OSError as exc:
                logger.warning("No se pudieron crear carpetas de trabajo en %s: %s", cfg.folder, exc)

        # Apply the computed threshold before building the preview so the first
        # table the user sees already matches the data distribution (avoids a
        # silent default like 30 m that leaves most photos "Fuera").
        applied_threshold: Optional[float] = None
        if suggested is not None and samples > 0:
            applied_threshold = float(suggested)
            self._apply_threshold_value(applied_threshold)

        parts = [f"Análisis completado: {len(items)} fotos"]
        if duplicates:
            parts.append(f"{duplicates} duplicadas detectadas")
        if applied_threshold is not None:
            method_label = _METHOD_LABELS.get(method, method)
            parts.append(f"umbral aplicado {applied_threshold:.1f} m ({method_label})")
        self.progress_bar.setValue(100)
        # Unlocked apply: finished runs before WorkerController.clear.
        self._apply_preview()
        # Preview refresh rewrites the status line; restore the analysis summary
        # so the operator sees that the auto-threshold was applied.
        preview_bits = self.status_message.text()
        summary = " · ".join(parts)
        self.status_message.setText(
            f"{summary}. {preview_bits}" if preview_bits else f"{summary}."
        )
        self._persist_state()
        self._save_session()
        self.sidebar.set_has_analysis(bool(items))
        self.tabs.setCurrentWidget(self.preview_tab)
        self._update_workflow_banner()
        notify_bits = [f"{len(items)} fotos analizadas"]
        if applied_threshold is not None:
            notify_bits.append(f"umbral {applied_threshold:.1f} m")
        if duplicates:
            notify_bits.append(f"{duplicates} duplicadas")
        self._notify("Análisis completado", " · ".join(notify_bits))

    @Slot(object)
    def _on_rename_finished(self, stats) -> None:
        self.sidebar.set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        outcome = classify_rename_outcome(stats if isinstance(stats, dict) else None)
        logger.info(
            "Renombrado finalizado: ok=%s skipped=%s errors=%s cancelled=%s",
            outcome.ok, outcome.skipped, outcome.errors, outcome.cancelled,
        )
        self.status_message.setText(outcome.status_line)
        cfg = self.sidebar.get_config()
        # Persist THIS run's mapping whenever disk kept renamed names — including
        # stuck ok==0 cases (metadata/rollback failure). Skipping those left
        # Undo pointed at a stale SQLite batch while CSV already had the stuck map.
        mapping = stats.get("mapping") if isinstance(stats, dict) else {}
        if mapping and cfg.folder:
            self._undo_history.record(cfg.folder, mapping)
        self._save_session()
        # Refresh Original/Nuevo/Destino now that paths changed on disk.
        if self._analysis_items:
            self._apply_preview()
        folder = cfg.folder if cfg else ""
        # Defer until WorkerController.clear() has run (finished is queued before
        # clear); otherwise «Deshacer ahora» hits the busy gate and no-ops.
        QTimer.singleShot(
            0,
            lambda o=outcome, f=folder: self._present_rename_outcome(o, f),
        )
        self._notify(outcome.dialog_title, outcome.status_line)

    def _present_rename_outcome(self, outcome, folder: str) -> None:
        """Surface empty / partial / success outcomes with recovery actions."""
        if outcome.is_empty:
            self._error(outcome.dialog_body)
            return
        if not outcome.is_partial:
            self._info(outcome.dialog_body)
            return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(outcome.dialog_title)
        box.setText(outcome.dialog_body)
        undo_btn = box.addButton("Deshacer ahora", QMessageBox.AcceptRole)
        open_btn = box.addButton("Abrir carpeta", QMessageBox.ActionRole)
        box.addButton("Cerrar", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is undo_btn:
            self._on_undo()
        elif clicked is open_btn and folder and os.path.isdir(folder):
            from PySide6.QtGui import QDesktopServices

            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    @Slot(object)
    def _on_undo_finished(self, payload) -> None:
        self.sidebar.set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        msg = payload.get("message", "") if isinstance(payload, dict) else str(payload)
        ok = payload.get("ok", False) if isinstance(payload, dict) else True
        self.status_message.setText(msg)
        (self._info if ok else self._error)(msg)

    @Slot(object)
    def _on_undo_history_finished(self, payload) -> None:
        self.sidebar.set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        if not isinstance(payload, dict):
            self._error("Respuesta de deshacer no válida.")
            return
        msg = payload.get("message", "")
        ok = bool(payload.get("ok"))
        entry_id = payload.get("entry_id")
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        # Keep the SQLite entry when anything remains unresolved so the user
        # can retry missing/conflict files instead of losing the mapping.
        fully_done = (
            ok
            and int(summary.get("missing", 0)) == 0
            and int(summary.get("conflict", 0)) == 0
        )
        if fully_done and entry_id is not None:
            self._undo_history.delete(int(entry_id))
        self.status_message.setText(msg)
        (self._info if ok else self._error)(msg)

    @Slot(object)
    def _on_auto_threshold_finished(self, payload) -> None:
        if not isinstance(payload, dict) or payload.get("threshold") is None:
            self._error(
                "No hay distancias válidas para calcular un umbral automático.\n"
                "Ejecuta un análisis con una carpeta que contenga imágenes con EXIF GPS."
            )
            return

        threshold = float(payload["threshold"])
        method = payload.get("method", "iqr_strict")
        samples = int(payload.get("samples", 0))
        min_d = float(payload.get("min", 0.0))
        max_d = float(payload.get("max", 0.0))
        mean_d = float(payload.get("mean", 0.0))
        median_d = float(payload.get("median", 0.0))
        p90 = float(payload.get("p90", 0.0))

        self._apply_threshold_value(threshold)
        distances = [it.distance for it in self._analysis_items if it.distance != float("inf")]
        self.sidebar.set_histogram(distances, threshold)

        method_label = _METHOD_LABELS.get(method, method)
        self.status_message.setText(
            f"Umbral automático: {threshold:.1f} m · {method_label} · "
            f"{samples} muestras · mediana {median_d:.1f} m · P90 {p90:.1f} m."
        )
        self._info(
            "Umbral automático propuesto\n\n"
            f"Valor: {threshold:.1f} m\n"
            f"Método: {method_label}\n"
            f"Muestras: {samples}\n"
            f"Rango observado: {min_d:.1f} – {max_d:.1f} m\n"
            f"Media: {mean_d:.1f} m · Mediana: {median_d:.1f} m · P90: {p90:.1f} m"
        )
        self._persist_state()
        if self.config_manager.config.auto_refresh_preview:
            self._debounced_refresh_preview()
        self._update_workflow_banner()

    @Slot(str)
    def _on_worker_failed(self, message: str) -> None:
        self.sidebar.set_busy(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self._error(message)
        self.status_message.setText(f"Error: {message}")

    # ------------------------------------------------------------------
    # Messaging helpers
    # ------------------------------------------------------------------
    def _info(self, message: str) -> None:
        QMessageBox.information(self, "Renombrador PKS", message)

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "Renombrador PKS", message)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    def closeEvent(self, event) -> None:  # noqa: N802
        self._worker_ctl.cancel()
        self._autosave_timer.stop()
        self._preview_debounce_timer.stop()
        try:
            self._persist_state()
            self._save_session()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Failed to persist state on close")
        super().closeEvent(event)
