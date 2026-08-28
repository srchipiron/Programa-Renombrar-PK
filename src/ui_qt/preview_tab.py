"""Preview tab with a sortable/filterable table, real EXIF thumbnails, context menu and keyboard navigation."""
from __future__ import annotations

import os
import threading
from typing import List, Optional

from PIL import Image, ExifTags
from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QModelIndex,
    QObject,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.models import PhotoItem

_COLUMNS = [
    ("include", "Incluir"),
    ("name", "Original"),
    ("new_name", "Nuevo nombre"),
    ("dest", "Destino"),
    ("pk_display", "PK"),
    ("distance", "Distancia (m)"),
    ("status", "Estado"),
]


class PreviewTableModel(QAbstractTableModel):
    """Model exposing the analyzed photos to the table view."""

    exclusion_changed = Signal(int, bool)

    def __init__(self) -> None:
        super().__init__()
        self._items: List[PhotoItem] = []
        self._preview: dict[str, str] = {}

    # Qt interface ----------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return len(_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                return _COLUMNS[section][1]
            if role == Qt.ToolTipRole and _COLUMNS[section][0] == "include":
                return "Incluir en el renombrado"
        if role == Qt.DisplayRole and orientation == Qt.Vertical:
            return section + 1
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # noqa: D401
        base = super().flags(index)
        if _COLUMNS[index.column()][0] == "include":
            return base | Qt.ItemIsUserCheckable
        return base

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: D401
        if not index.isValid():
            return None
        item = self._items[index.row()]
        key = _COLUMNS[index.column()][0]

        if role == Qt.CheckStateRole and key == "include":
            return Qt.Checked if not item.excluded else Qt.Unchecked

        if role in (Qt.DisplayRole, Qt.EditRole):
            if key == "include":
                return ""
            if key == "name":
                return item.name + (" · duplicada" if item.duplicate_of else "")
            if key == "new_name":
                if item.excluded:
                    return "(excluida)"
                if item.virtual:
                    return "(fotograma de vídeo — no se renombra)"
                return self._preview.get(item.path, "") or "(fuera de umbral)"
            if key == "dest":
                if item.excluded or not item.is_inside_threshold:
                    return "—"
                return item.dest_rel or "(raíz)"
            if key == "pk_display":
                return item.pk_display or "—"
            if key == "distance":
                return "∞" if item.distance == float("inf") else f"{item.distance:.2f}"
            if key == "status":
                if item.excluded:
                    return "Excluida"
                return "Dentro" if item.is_inside_threshold else "Fuera"

        if role == Qt.AccessibleTextRole:
            if key == "include":
                return "Incluida para renombrar" if not item.excluded else "Excluida del renombrado"
            if key == "status":
                if item.excluded:
                    return "Excluida manualmente"
                return "Dentro del umbral" if item.is_inside_threshold else "Fuera del umbral"

        if role == Qt.ForegroundRole:
            if key == "status":
                if item.excluded:
                    return QColor("#94a3b8")
                return QColor("#10b981" if item.is_inside_threshold else "#ef4444")
            if key == "name" and item.duplicate_of:
                return QColor("#f59e0b")

        if role == Qt.ToolTipRole:
            if item.duplicate_of and key in ("name", "status"):
                return f"Duplicada de: {item.duplicate_of}"
            if item.sidecars and key == "name":
                return "Sidecars: " + ", ".join(os.path.basename(p) for p in item.sidecars)

        if role == Qt.UserRole:
            return item

        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802, D401
        if role == Qt.CheckStateRole and _COLUMNS[index.column()][0] == "include":
            item = self._items[index.row()]
            item.excluded = value != Qt.Checked
            self.dataChanged.emit(index, index, [Qt.CheckStateRole, Qt.DisplayRole])
            name_idx = self.index(index.row(), 1)
            preview_idx = self.index(index.row(), len(_COLUMNS) - 1)
            self.dataChanged.emit(name_idx, preview_idx, [Qt.DisplayRole, Qt.ForegroundRole])
            self.exclusion_changed.emit(index.row(), item.excluded)
            return True
        return super().setData(index, value, role)

    # Public helpers --------------------------------------------------
    def set_items(self, items: List[PhotoItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def update_preview(self, preview_by_path: dict[str, str]) -> None:
        self._preview = dict(preview_by_path)
        if self._items:
            top_left = self.index(0, 1)
            bottom_right = self.index(len(self._items) - 1, len(_COLUMNS) - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

    def items(self) -> List[PhotoItem]:
        return list(self._items)

    def item_at(self, row: int) -> Optional[PhotoItem]:
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def set_all_excluded(self, excluded: bool) -> None:
        if not self._items:
            return
        for it in self._items:
            it.excluded = excluded
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._items) - 1, len(_COLUMNS) - 1)
        self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole, Qt.DisplayRole, Qt.ForegroundRole])

    def exclude_duplicates(self) -> int:
        """Mark every flagged duplicate as excluded. Returns how many changed."""
        if not self._items:
            return 0
        changed = 0
        for it in self._items:
            if it.duplicate_of and not it.excluded:
                it.excluded = True
                changed += 1
        if changed:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._items) - 1, len(_COLUMNS) - 1)
            self.dataChanged.emit(
                top_left,
                bottom_right,
                [Qt.CheckStateRole, Qt.DisplayRole, Qt.ForegroundRole],
            )
        return changed


class _ThumbnailLoader(QObject):
    """Loads scaled EXIF-aware thumbnails in a background worker thread.
    
    Drops superseded requests so rapid arrow-key scrolling doesn't build
    up a backlog of thread allocations or disk reads.
    """

    ready = Signal(str, object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._pending_path: Optional[str] = None
        self._pending_size: int = 360
        self._worker_thread: Optional[threading.Thread] = None
        self._running = True

    def load(self, path: str, max_size: int) -> None:
        with self._lock:
            self._pending_path = path
            self._pending_size = max_size
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(target=self._run, daemon=True)
                self._worker_thread.start()

    def _run(self) -> None:
        while self._running:
            with self._lock:
                path = self._pending_path
                size = self._pending_size
                self._pending_path = None
            if not path:
                break
            pixmap = _read_thumbnail(path, size)
            with self._lock:
                is_latest = (self._pending_path is None or self._pending_path == path)
            if is_latest:
                self.ready.emit(path, pixmap)


def _read_thumbnail(path: str, max_size: int) -> Optional[QPixmap]:
    try:
        with Image.open(path) as img:
            img.draft("RGB", (max_size, max_size))
            try:
                orientation_key = None
                for k, v in ExifTags.TAGS.items():
                    if v == "Orientation":
                        orientation_key = k
                        break
                exif = img._getexif() if hasattr(img, "_getexif") else None
                if exif and orientation_key in exif:
                    orient = exif[orientation_key]
                    if orient == 3:
                        img = img.rotate(180, expand=True)
                    elif orient == 6:
                        img = img.rotate(270, expand=True)
                    elif orient == 8:
                        img = img.rotate(90, expand=True)
            except Exception:
                pass
            img = img.convert("RGB")
            img.thumbnail((max_size, max_size))
            data = img.tobytes("raw", "RGB")
            qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
            return QPixmap.fromImage(qimg.copy())
    except Exception:
        return None


class PreviewTab(QWidget):
    """Preview tab combining a table, filters, context menu and details pane."""

    open_image_requested = Signal(str)
    show_on_map_requested = Signal(object)  # PhotoItem
    exclusion_changed = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filtrar:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Buscar por nombre, PK o estado…")
        filter_row.addWidget(self.filter_edit, 1)

        filter_row.addWidget(QLabel("Estado:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Todos", "Solo Dentro", "Solo Fuera", "Solo Duplicadas"])
        filter_row.addWidget(self.status_filter)

        self.include_all_btn = QPushButton("Incluir todas")
        self.include_all_btn.setToolTip("Marcar todas las fotos para renombrar")
        self.include_all_btn.clicked.connect(self._on_include_all)
        filter_row.addWidget(self.include_all_btn)

        self.exclude_all_btn = QPushButton("Excluir todas")
        self.exclude_all_btn.setToolTip("Desmarcar todas las fotos")
        self.exclude_all_btn.clicked.connect(self._on_exclude_all)
        filter_row.addWidget(self.exclude_all_btn)

        self.exclude_dupes_btn = QPushButton("Excluir duplicadas")
        self.exclude_dupes_btn.setToolTip(
            "Excluir del renombrado las fotos detectadas como duplicadas "
            "(mismo GPS y marca de tiempo cercana)"
        )
        self.exclude_dupes_btn.clicked.connect(self._on_exclude_duplicates)
        filter_row.addWidget(self.exclude_dupes_btn)

        self.count_label = QLabel("0 fotos")
        self.count_label.setProperty("role", "muted")
        filter_row.addWidget(self.count_label)

        layout.addLayout(filter_row)

        self.content_stack = QStackedWidget()
        layout.addWidget(self.content_stack, 1)

        self.empty_state = QLabel(
            "<p style='text-align:center;'><b>Sin análisis todavía</b></p>"
            "<p style='text-align:center;'>Selecciona carpeta y traza KML en el panel izquierdo. "
            "Cuando ambos estén listos, pulsa <b>Analizar (F5)</b>.</p>"
            "<p style='text-align:center; color:#64748b;'>El umbral se ajusta solo con los datos; "
            "aquí verás nombres propuestos, filtros y miniaturas.</p>"
        )
        self.empty_state.setObjectName("previewEmpty")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignCenter)
        self.content_stack.addWidget(self.empty_state)

        table_page = QWidget()
        table_layout = QVBoxLayout(table_page)
        table_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        table_layout.addWidget(splitter)
        self.content_stack.addWidget(table_page)

        self.model = PreviewTableModel()
        self.model.exclusion_changed.connect(lambda *_args: self.exclusion_changed.emit())
        self.proxy = QSortFilterProxyModel()
        self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)

        self.table = QTableView()
        self.table.setAccessibleName("Vista previa de fotos analizadas")
        self.table.setAccessibleDescription(
            "Tabla con fotos, nombres propuestos, distancia al PK y estado dentro o fuera del umbral"
        )
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.doubleClicked.connect(self._open_current)

        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().resizeSection(0, 32)
        self.table.verticalHeader().setVisible(False)
        splitter.addWidget(self.table)

        # Details pane
        details = QFrame()
        details.setObjectName("thumbFrame")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(12, 12, 12, 12)
        details_layout.setSpacing(8)

        self.thumb_label = QLabel("Selecciona una foto para ver la miniatura.")
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setMinimumSize(260, 260)
        details_layout.addWidget(self.thumb_label)

        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        details_layout.addWidget(self.details_label)

        btn_row = QHBoxLayout()
        self.open_btn = QPushButton("Abrir imagen")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_current)
        btn_row.addWidget(self.open_btn)

        self.map_btn = QPushButton("Ver en mapa")
        self.map_btn.setEnabled(False)
        self.map_btn.clicked.connect(self._show_current_on_map)
        btn_row.addWidget(self.map_btn)
        details_layout.addLayout(btn_row)

        details_layout.addStretch(1)

        splitter.addWidget(details)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Signals
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.status_filter.currentIndexChanged.connect(self._apply_filter)
        self.table.clicked.connect(self._on_row_clicked)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row_changed)

        self._thumb_loader = _ThumbnailLoader(self)
        self._thumb_loader.ready.connect(self._apply_thumbnail_data)
        self._current_item: Optional[PhotoItem] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_items(self, items: List[PhotoItem]) -> None:
        self.model.set_items(items)
        self.refresh_counts()
        self._current_item = None
        self.details_label.setText("")
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText("Selecciona una foto para ver la miniatura.")
        self.open_btn.setEnabled(False)
        self.map_btn.setEnabled(False)
        self.content_stack.setCurrentIndex(1 if items else 0)

    def update_preview(
        self,
        items: List[PhotoItem],
        plan: Optional[dict[str, str]] = None,
    ) -> None:
        """Update the ``Nuevo nombre`` column with the real F7 plan when given.

        ``plan`` maps ``item.path -> display label`` (final filename with
        optional relative destination). Without it, falls back to stems.
        """
        if plan is not None:
            preview = dict(plan)
        else:
            preview = {it.path: it.new_name_base for it in items if it.new_name_base}
        self.model.update_preview(preview)
        self.refresh_counts()
        if self._current_item is not None:
            self._refresh_details(self._current_item)

    def refresh_counts(self) -> None:
        items = self.model.items()
        total = len(items)
        excluded = sum(1 for it in items if it.excluded)
        inside = sum(1 for it in items if it.is_inside_threshold and not it.excluded)
        duplicates = sum(1 for it in items if it.duplicate_of)
        bits = [f"{total} fotos", f"{inside} incluidas"]
        if excluded:
            bits.append(f"{excluded} excluidas")
        if duplicates:
            bits.append(f"{duplicates} duplicadas")
        self.count_label.setText(" · ".join(bits))

    def items(self) -> List[PhotoItem]:
        return self.model.items()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    @Slot()
    def _on_include_all(self) -> None:
        self.model.set_all_excluded(False)
        self.refresh_counts()
        self.exclusion_changed.emit()

    @Slot()
    def _on_exclude_all(self) -> None:
        self.model.set_all_excluded(True)
        self.refresh_counts()
        self.exclusion_changed.emit()

    @Slot()
    def _on_exclude_duplicates(self) -> None:
        self.model.exclude_duplicates()
        self.refresh_counts()
        self.exclusion_changed.emit()

    @Slot()
    def _apply_filter(self) -> None:
        pattern = self.filter_edit.text().strip()
        self.proxy.setFilterFixedString(pattern)

        status = self.status_filter.currentText()
        items = self.model.items()
        if status == "Solo Dentro":
            self._hide_rows([i for i, it in enumerate(items) if not it.is_inside_threshold])
        elif status == "Solo Fuera":
            self._hide_rows([i for i, it in enumerate(items) if it.is_inside_threshold])
        elif status == "Solo Duplicadas":
            self._hide_rows([i for i, it in enumerate(items) if not it.duplicate_of])
        else:
            self._hide_rows([])

    def _hide_rows(self, rows_to_hide: List[int]) -> None:
        hidden_source = set(rows_to_hide)
        for proxy_row in range(self.proxy.rowCount()):
            source_row = self.proxy.mapToSource(self.proxy.index(proxy_row, 0)).row()
            self.table.setRowHidden(proxy_row, source_row in hidden_source)

    def _on_row_clicked(self, index: QModelIndex) -> None:
        self._select_index(index)

    def _on_current_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if current.isValid():
            self._select_index(current)

    def _select_index(self, index: QModelIndex) -> None:
        source_index = self.proxy.mapToSource(index)
        item = self.model.item_at(source_index.row())
        if not item:
            return
        self._current_item = item
        self._refresh_details(item)

    def _refresh_details(self, item: PhotoItem) -> None:
        distance = "∞" if item.distance == float("inf") else f"{item.distance:.2f} m"
        state = "Dentro del umbral" if item.is_inside_threshold else "Fuera del umbral"
        alt_text = f"<br>Altitud rel: {item.rel_altitude:.1f} m" if item.rel_altitude is not None else ""
        view_text = f" ({item.view_label})" if item.view_label else ""
        planned = self.model._preview.get(item.path) or item.new_name_base or "—"
        dest = item.dest_rel or ("(raíz)" if item.is_inside_threshold and item.new_name_base else "—")
        details = (
            f"<b>{item.name}</b>{view_text}<br>"
            f"Latitud: {item.lat:.6f}<br>"
            f"Longitud: {item.lon:.6f}{alt_text}<br>"
            f"Fecha EXIF: {item.date_str or '—'} {item.time_str or ''}<br>"
            f"PK: {item.pk_display or '—'}<br>"
            f"Distancia: {distance}<br>"
            f"Estado: {state}<br>"
            f"Destino: <code>{dest}</code><br>"
            f"Nuevo nombre: <code>{planned}</code>"
        )
        self.details_label.setText(details)
        self.thumb_label.setText("Cargando miniatura…")
        self.thumb_label.setPixmap(QPixmap())
        self.open_btn.setEnabled(True)
        self.map_btn.setEnabled(True)

        self._thumb_loader.load(item.path, 360)

    @Slot(str, object)
    def _apply_thumbnail_data(self, path: str, pixmap) -> None:
        if not self._current_item or self._current_item.path != path:
            return
        if pixmap is None or pixmap.isNull():
            self.thumb_label.setText("No se pudo generar la miniatura.")
            self.thumb_label.setPixmap(QPixmap())
            return
        scaled = pixmap.scaled(
            self.thumb_label.width(),
            self.thumb_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)
        self.thumb_label.setText("")

    def _open_current(self) -> None:
        if not self._current_item:
            return
        if os.path.exists(self._current_item.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_item.path))
            self.open_image_requested.emit(self._current_item.path)

    def _open_in_explorer(self) -> None:
        if not self._current_item or not os.path.exists(self._current_item.path):
            return
        folder = os.path.dirname(self._current_item.path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _show_current_on_map(self) -> None:
        if self._current_item:
            self.show_on_map_requested.emit(self._current_item)

    def _on_context_menu(self, pos) -> None:
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        source_index = self.proxy.mapToSource(index)
        item = self.model.item_at(source_index.row())
        if not item:
            return

        menu = QMenu(self)
        open_act = menu.addAction("🖼️  Abrir imagen")
        open_act.triggered.connect(self._open_current)

        explorer_act = menu.addAction("📁  Mostrar en el Explorador")
        explorer_act.triggered.connect(self._open_in_explorer)

        map_act = menu.addAction("🗺️  Ver en el mapa (F8)")
        map_act.triggered.connect(self._show_current_on_map)

        menu.addSeparator()
        toggle_label = "❌  Excluir selección" if not item.excluded else "✅  Incluir selección"
        toggle_act = menu.addAction(toggle_label)
        toggle_act.triggered.connect(self._toggle_selected_inclusions)

        menu.addSeparator()
        copy_orig_act = menu.addAction("📋  Copiar nombre original")
        copy_orig_act.triggered.connect(lambda: QApplication.clipboard().setText(item.name))

        if item.new_name_base:
            planned = self.model._preview.get(item.path) or item.new_name_base
            copy_new_act = menu.addAction("📋  Copiar nuevo nombre")
            copy_new_act.triggered.connect(lambda: QApplication.clipboard().setText(planned))

        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _toggle_selected_inclusions(self) -> None:
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            return
        for proxy_idx in selected_indexes:
            source_idx = self.proxy.mapToSource(proxy_idx)
            item = self.model.item_at(source_idx.row())
            if item:
                new_state = Qt.Unchecked if not item.excluded else Qt.Checked
                include_idx = self.model.index(source_idx.row(), 0)
                self.model.setData(include_idx, new_state, Qt.CheckStateRole)
        self.refresh_counts()
        self.exclusion_changed.emit()
