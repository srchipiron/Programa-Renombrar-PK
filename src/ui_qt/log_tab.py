"""Log tab wired to the real Python logger via :class:`QtLogHandler`."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .log_handler import QtLogHandler

_LEVEL_COLORS = {
    "DEBUG": "#64748b",
    "INFO": "#e6edf3",
    "WARNING": "#f59e0b",
    "ERROR": "#ef4444",
    "CRITICAL": "#ef4444",
}

_LEVEL_ORDER = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LogTab(QWidget):
    """A searchable, level-filterable log viewer backed by the root logger."""

    log_emitted = Signal(str, str)

    def __init__(self, handler: QtLogHandler, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.handler = handler

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Nivel mínimo:"))
        self.level_combo = QComboBox()
        self.level_combo.addItems(_LEVEL_ORDER)
        self.level_combo.setCurrentText("INFO")
        self.level_combo.currentTextChanged.connect(self._on_level_changed)
        toolbar.addWidget(self.level_combo)

        toolbar.addStretch(1)

        self.autoscroll_check = QCheckBox("Auto-scroll")
        self.autoscroll_check.setChecked(True)
        toolbar.addWidget(self.autoscroll_check)

        self.save_btn = QPushButton("Guardar…")
        self.save_btn.clicked.connect(self._save_logs)
        toolbar.addWidget(self.save_btn)

        self.clear_btn = QPushButton("Limpiar")
        self.clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(self.clear_btn)

        layout.addLayout(toolbar)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setFont(self.font())
        self.view.setStyleSheet(
            "QPlainTextEdit { background:#0b1220; border:1px solid #1e293b; "
            "border-radius:8px; padding:8px; font-family:'Fira Code','Consolas',monospace; }"
        )
        layout.addWidget(self.view, 1)

        handler.message.connect(self._on_log_message)
        self._on_level_changed(self.level_combo.currentText())

    # ------------------------------------------------------------------
    @Slot(str, str)
    def _on_log_message(self, level: str, message: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {level:<8} {message}"
        color = _LEVEL_COLORS.get(level, "#e6edf3")

        cursor = self.view.textCursor()
        cursor.movePosition(QTextCursor.End)
        fmt = QTextCharFormat()
        fmt.setForeground(Qt.GlobalColor.white)
        cursor.insertHtml(
            f'<span style="color:{color};">{self._escape(line)}</span><br>'
        )
        if self.autoscroll_check.isChecked():
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    @staticmethod
    def _escape(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @Slot(str)
    def _on_level_changed(self, level: str) -> None:
        numeric = getattr(logging, level.upper(), logging.INFO)
        self.handler.setLevel(numeric)

    @Slot()
    def _save_logs(self) -> None:
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar registro",
            f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            "Texto (*.txt);;Todos los archivos (*)",
        )
        if not fname:
            return
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(self.view.toPlainText())
        except OSError as exc:
            logging.getLogger(__name__).error("No se pudo guardar el registro: %s", exc)

    @Slot()
    def _clear(self) -> None:
        self.view.clear()
