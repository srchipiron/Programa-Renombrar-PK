"""Sidebar widget with file selection, parameters and action buttons."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.config import ConfigManager
from ..core.renamer_logic import AUTO_THRESHOLD_MAX, render_template
from .histogram import DistanceHistogram



@dataclass
class SidebarConfig:
    folder: str
    kml_file: str
    threshold: float
    suffix: str
    create_backup: bool


def _variant(btn: QPushButton, variant: str) -> QPushButton:
    btn.setProperty("variant", variant)
    return btn


def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def _hline() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setProperty("role", "hline")
    return line


class _PathSelector(QWidget):
    """Line edit + browse button with light validation styling."""

    changed = Signal(str)

    def __init__(
        self,
        label: str,
        tooltip: str,
        file_mode: str,
        file_filter: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.file_mode = file_mode
        self.file_filter = file_filter

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        layout.addWidget(QLabel(label))

        row = QHBoxLayout()
        row.setSpacing(6)

        self.edit = QLineEdit()
        self.edit.setPlaceholderText("No seleccionado")
        self.edit.setToolTip(tooltip)
        self.edit.textChanged.connect(self._on_text_changed)
        row.addWidget(self.edit, 1)

        self.browse_btn = QPushButton("Examinar")
        self.browse_btn.setToolTip("Seleccionar desde disco")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.browse_btn)

        layout.addLayout(row)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, text: str) -> None:
        self.edit.setText(text)

    def _on_text_changed(self, text: str) -> None:
        state = "" if not text else ("ok" if os.path.exists(text) else "bad")
        self.edit.setProperty("state", state)
        self.edit.style().unpolish(self.edit)
        self.edit.style().polish(self.edit)
        self.changed.emit(text)

    def _browse(self) -> None:
        current = self.value()
        start_dir = current if current and os.path.exists(current) else ""
        if self.file_mode == "folder":
            selected = QFileDialog.getExistingDirectory(self, "Seleccionar carpeta", start_dir)
        else:
            start = start_dir or os.path.dirname(current) if current else ""
            selected, _ = QFileDialog.getOpenFileName(
                self, "Seleccionar archivo", start, self.file_filter or ""
            )
        if selected:
            self.set_value(selected)


class Sidebar(QWidget):
    """Left side panel with all user-facing controls."""

    analyze_requested = Signal()
    preview_requested = Signal()
    process_requested = Signal()
    cancel_requested = Signal()
    undo_requested = Signal()
    export_csv_requested = Signal()
    generate_map_requested = Signal()
    auto_threshold_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self, config_manager: ConfigManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config_manager = config_manager

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.workflow_banner = QLabel(
            "<b>Empieza aquí</b><br>"
            "1. Carpeta de imágenes + traza KML<br>"
            "2. <b>Analizar</b> (F5) — aplica umbral automático<br>"
            "3. Revisa y <b>Renombra</b> (F7)"
        )
        self.workflow_banner.setObjectName("workflowBanner")
        self.workflow_banner.setWordWrap(True)
        self.workflow_banner.setProperty("level", "info")
        layout.addWidget(self.workflow_banner)

        # Files section
        layout.addWidget(_section_title("ARCHIVOS"))
        self.folder_selector = _PathSelector(
            "Carpeta de imágenes",
            "Carpeta raíz que contiene las imágenes a procesar",
            file_mode="folder",
        )
        layout.addWidget(self.folder_selector)

        open_folder_btn = QPushButton("Abrir carpeta en el explorador")
        open_folder_btn.clicked.connect(self.open_folder_requested)
        layout.addWidget(open_folder_btn)

        self.kml_selector = _PathSelector(
            "Archivo KML/KMZ/GeoJSON",
            "Archivo con la traza y los puntos kilométricos",
            file_mode="file",
            file_filter="Datos espaciales (*.kml *.kmz *.geojson *.json);;Todos los archivos (*.*)",
        )
        layout.addWidget(self.kml_selector)

        layout.addWidget(_hline())

        # Configuration
        layout.addWidget(_section_title("PARÁMETROS"))

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Umbral (m):"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(1.0, AUTO_THRESHOLD_MAX)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSingleStep(5.0)
        self.threshold_spin.setValue(config_manager.config.threshold)
        self.threshold_spin.setToolTip("Distancia máxima (m) para considerar una foto 'dentro'")
        threshold_row.addWidget(self.threshold_spin, 1)
        layout.addLayout(threshold_row)

        self.auto_threshold_btn = QPushButton("Calcular umbral automáticamente")
        self.auto_threshold_btn.setToolTip("Requiere un análisis previo")
        self.auto_threshold_btn.clicked.connect(self.auto_threshold_requested)
        layout.addWidget(self.auto_threshold_btn)

        self.histogram = DistanceHistogram()
        layout.addWidget(self.histogram)

        suffix_row = QVBoxLayout()
        suffix_row.setSpacing(4)
        suffix_row.addWidget(QLabel("Plantilla / sufijo:"))
        self.suffix_edit = QLineEdit(config_manager.config.last_suffix)
        self.suffix_edit.setToolTip(
            "Plantilla. Si incluye tokens se usa tal cual; si no, se añade "
            "al PK como sufijo.\nTokens: {pk}, {pk_raw}, {km}, {m}, {view}, {original}, "
            "{date}, {time}, {camera}, {alt}, {dist}, {sequence:02d}, {suffix}.\n"
            "Ejemplo: {pk}_{date}_{sequence:02d}"
        )
        suffix_row.addWidget(self.suffix_edit)

        self.sample_preview_label = QLabel("")
        self.sample_preview_label.setStyleSheet("color: #60a5fa; font-size: 8pt; font-family: monospace;")
        self.sample_preview_label.setWordWrap(True)
        suffix_row.addWidget(self.sample_preview_label)

        presets_row = QHBoxLayout()
        presets_row.setSpacing(4)
        for label, val in [("[PK]-MES26", "[PK]-AGO26"), ("{pk}_{date}", "{pk}_{date}"), ("{pk}_{seq:02d}", "{pk}_{sequence:02d}")]:
            p_btn = QPushButton(label)
            p_btn.setStyleSheet("font-size: 8pt; padding: 2px 4px;")
            p_btn.clicked.connect(lambda _c=False, v=val: self.suffix_edit.setText(v))
            presets_row.addWidget(p_btn)
        suffix_row.addLayout(presets_row)

        self.suffix_edit.textChanged.connect(self._update_sample_preview)
        self._update_sample_preview(self.suffix_edit.text())

        layout.addLayout(suffix_row)


        self.backup_check = QCheckBox("Crear copia de seguridad")
        self.backup_check.setChecked(config_manager.config.create_backup)
        self.backup_check.setToolTip("Guarda una copia de cada archivo original antes de renombrar")
        layout.addWidget(self.backup_check)

        layout.addWidget(_hline())

        # Actions
        layout.addWidget(_section_title("ACCIONES"))

        self.analyze_btn = _variant(QPushButton("Analizar imágenes  (F5)"), "primary")
        self.analyze_btn.clicked.connect(self.analyze_requested)
        layout.addWidget(self.analyze_btn)

        self.preview_btn = QPushButton("Actualizar vista previa  (F6)")
        self.preview_btn.clicked.connect(self.preview_requested)
        layout.addWidget(self.preview_btn)

        self.process_btn = _variant(QPushButton("Procesar renombrado  (F7)"), "success")
        self.process_btn.clicked.connect(self.process_requested)
        layout.addWidget(self.process_btn)

        self.undo_btn = QPushButton("Deshacer renombrado")
        self.undo_btn.setToolTip(
            "Revierte el último lote en esta carpeta (historial interno o CSV). "
            "Para operaciones antiguas usa Historial… (Ctrl+H)."
        )
        self.undo_btn.clicked.connect(self.undo_requested)
        layout.addWidget(self.undo_btn)

        self.cancel_btn = _variant(QPushButton("Cancelar operación  (Esc)"), "danger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested)
        layout.addWidget(self.cancel_btn)

        layout.addWidget(_hline())

        # Outputs
        layout.addWidget(_section_title("SALIDAS"))

        self.export_btn = QPushButton("Exportar resultados a CSV  (Ctrl+E)")
        self.export_btn.clicked.connect(self.export_csv_requested)
        layout.addWidget(self.export_btn)

        self.map_btn = QPushButton("Generar mapa interactivo  (F8)")
        self.map_btn.clicked.connect(self.generate_map_requested)
        layout.addWidget(self.map_btn)

        layout.addStretch(1)

        self._has_analysis = False
        self.folder_selector.changed.connect(lambda _t: self._apply_input_guards())
        self.kml_selector.changed.connect(lambda _t: self._apply_input_guards())
        self._apply_analysis_guards()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def set_workflow_hint(self, html: str, *, level: str = "info") -> None:
        """Update the guided workflow banner (info | success | warning)."""
        self.workflow_banner.setProperty("level", level)
        self.workflow_banner.setText(html)
        self.workflow_banner.style().unpolish(self.workflow_banner)
        self.workflow_banner.style().polish(self.workflow_banner)

    def set_has_analysis(self, has: bool) -> None:
        """Enable post-analysis actions and refresh guard tooltips."""
        self._has_analysis = has
        self._apply_analysis_guards()

    def inputs_ready(self) -> tuple[bool, bool]:
        """Return ``(folder_ok, kml_ok)`` for the current path fields."""
        folder = self.folder_selector.value()
        kml = self.kml_selector.value()
        return (
            bool(folder and os.path.isdir(folder)),
            bool(kml and os.path.isfile(kml)),
        )

    def _apply_input_guards(self) -> None:
        """Enable Analizar only when folder + traza exist (unless busy)."""
        if self.cancel_btn.isEnabled():
            return
        folder_ok, kml_ok = self.inputs_ready()
        ready = folder_ok and kml_ok
        self.analyze_btn.setEnabled(ready)
        if ready:
            self.analyze_btn.setToolTip(
                "Extrae EXIF GPS, calcula distancias y aplica un umbral automático (F5)."
            )
            return
        missing: list[str] = []
        if not folder_ok:
            missing.append("una carpeta de imágenes válida")
        if not kml_ok:
            missing.append("un archivo KML/KMZ/GeoJSON válido")
        self.analyze_btn.setToolTip(
            "Selecciona " + " y ".join(missing) + " para poder analizar."
        )

    def _apply_analysis_guards(self) -> None:
        if self.cancel_btn.isEnabled():
            return
        self._apply_input_guards()
        needs = "Ejecuta primero un análisis (F5)."
        post_actions = (
            (self.preview_btn, "Recalcula nombres y el histograma con el umbral actual."),
            (self.process_btn, "Aplica el renombrado a las fotos incluidas en la vista previa."),
            (self.auto_threshold_btn, "Recalcula el umbral a partir de las distancias del análisis."),
            (self.export_btn, "Exporta la tabla actual a CSV."),
            (self.map_btn, "Genera el mapa interactivo con las fotos analizadas."),
        )
        for btn, tip in post_actions:
            if self._has_analysis:
                btn.setEnabled(True)
                btn.setToolTip(tip)
            else:
                btn.setEnabled(False)
                btn.setToolTip(needs)

    def get_config(self) -> SidebarConfig:
        return SidebarConfig(
            folder=self.folder_selector.value(),
            kml_file=self.kml_selector.value(),
            threshold=float(self.threshold_spin.value()),
            suffix=self.suffix_edit.text().strip(),
            create_backup=self.backup_check.isChecked(),
        )

    def set_values(self, *, folder: str = "", kml_file: str = "",
                   threshold: Optional[float] = None, suffix: Optional[str] = None,
                   create_backup: Optional[bool] = None) -> None:
        if folder:
            self.folder_selector.set_value(folder)
        if kml_file:
            self.kml_selector.set_value(kml_file)
        if threshold is not None:
            spin = self.threshold_spin
            spin.blockSignals(True)
            try:
                spin.setValue(threshold)
            finally:
                spin.blockSignals(False)
        if suffix is not None:
            self.suffix_edit.setText(suffix)
        if create_backup is not None:
            self.backup_check.setChecked(create_backup)
        self._apply_input_guards()

    def set_histogram(self, distances, threshold: float) -> None:
        self.histogram.set_data(list(distances or []), float(threshold))

    def set_busy(self, busy: bool) -> None:
        for btn in (self.analyze_btn, self.preview_btn, self.process_btn,
                    self.undo_btn, self.export_btn, self.map_btn,
                    self.auto_threshold_btn):
            btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        if not busy:
            self._apply_analysis_guards()

    def _update_sample_preview(self, text: str) -> None:
        template = text.strip() or "{pk}"
        clean_tpl = "{pk}_{suffix}" if ("{" not in template and "[" not in template and template) else template
        sample_context = {
            "pk": "PK-22+600",
            "pk_raw": "22+600",
            "km": 22,
            "m": "600",
            "suffix": template,
            "date": "20260820",
            "time": "143000",
            "original": "DJI_001",
            "camera": "Mavic 3E",
            "view": "TI",
            "lat": "37.816741",
            "lon": "-0.967474",
            "dist": "12.5",
            "alt": "115.0",
        }
        res = render_template(clean_tpl, sample_context)
        self.sample_preview_label.setText(f"Muestra: {res}.jpg")

