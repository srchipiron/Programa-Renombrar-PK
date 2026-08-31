"""Dialog to import video subtitle (SRT) files and produce PhotoItems.

The underlying :class:`VideoExtractor` already understands DJI/Autel SRT
subtitles embedded with GPS coordinates.  This dialog exposes the feature
in the UI: the user picks a .srt file, previews a handful of parsed
points, and confirms to inject them into the current analysis list.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.models import PhotoItem
from ..core.video_extractor import VideoExtractor


class VideoImportDialog(QDialog):
    """Pick an SRT subtitle file, preview points, confirm import."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Importar vídeo (SRT con GPS)")
        self.resize(560, 440)

        self._items: List[PhotoItem] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        info = QLabel(
            "Selecciona un archivo .srt exportado por tu dron (DJI/Autel).\n"
            "Se extraerán los puntos GPS como 'fotos virtuales' que podrás "
            "cruzar con la traza KML y renombrar."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        row = QHBoxLayout()
        row.addWidget(QLabel("Archivo SRT:"))
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        row.addWidget(self.path_edit, 1)
        self.browse_btn = QPushButton("Examinar…")
        self.browse_btn.clicked.connect(self._browse)
        row.addWidget(self.browse_btn)
        layout.addLayout(row)

        self.preview = QListWidget()
        layout.addWidget(self.preview, 1)

        self.status = QLabel("Aún no se ha cargado ningún archivo.")
        self.status.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self.status)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._ok_button = buttons.button(QDialogButtonBox.Ok)
        self._ok_button.setEnabled(False)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Seleccionar SRT", "",
            "Subtítulos (*.srt);;Todos los archivos (*.*)",
        )
        if not path:
            return
        self.path_edit.setText(path)
        self._load(path)

    def _load(self, path: str) -> None:
        try:
            items = VideoExtractor().parse_srt(path)
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.warning(self, "Error", f"No se pudo leer el SRT:\n{exc}")
            return

        self._items = items
        self.preview.clear()
        for it in items[:200]:
            self.preview.addItem(
                f"{it.name}  ·  {it.lat:.6f}, {it.lon:.6f}  ·  {it.time_str}"
            )

        if not items:
            self.status.setText("No se han detectado puntos GPS válidos en el archivo.")
            self._ok_button.setEnabled(False)
        else:
            more = f"  (mostrando 200 de {len(items)})" if len(items) > 200 else ""
            self.status.setText(f"{len(items)} puntos GPS extraídos.{more}")
            self._ok_button.setEnabled(True)

    def result_items(self) -> List[PhotoItem]:
        return list(self._items)
