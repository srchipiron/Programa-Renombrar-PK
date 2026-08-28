"""Dialog that lists previous rename operations and applies undo."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .undo_history import UndoHistory, apply_undo


class UndoHistoryDialog(QDialog):
    """Browse and roll back past rename operations stored in SQLite."""

    def __init__(self, history: UndoHistory, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Historial de renombrados")
        self.resize(720, 420)
        self._history = history

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(QLabel(
            "Selecciona una operación para revertirla. El programa buscará los "
            "archivos dentro de la carpeta y restaurará los nombres originales."
        ))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Fecha", "Carpeta", "Fotos"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        self.undo_btn = QPushButton("Revertir esta operación")
        self.undo_btn.clicked.connect(self._on_undo)
        actions.addWidget(self.undo_btn)

        self.delete_btn = QPushButton("Eliminar del historial")
        self.delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(self.delete_btn)

        actions.addStretch(1)

        self.close_btn = QPushButton("Cerrar")
        self.close_btn.clicked.connect(self.accept)
        actions.addWidget(self.close_btn)

        layout.addLayout(actions)

        self._reload()

    def _reload(self) -> None:
        self.tree.clear()
        for entry in self._history.list_entries():
            node = QTreeWidgetItem([entry.timestamp_str, entry.folder, str(entry.total)])
            node.setData(0, Qt.UserRole, entry)
            self.tree.addTopLevelItem(node)
        self.undo_btn.setEnabled(self.tree.topLevelItemCount() > 0)
        self.delete_btn.setEnabled(self.tree.topLevelItemCount() > 0)

    def _selected_entry(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole)

    def _on_undo(self) -> None:
        entry = self._selected_entry()
        if not entry:
            QMessageBox.information(self, "Historial", "Selecciona una operación primero.")
            return
        ok = QMessageBox.question(
            self, "Revertir",
            f"¿Revertir la operación del {entry.timestamp_str}?\n"
            f"Carpeta: {entry.folder}\n"
            f"Fotos: {entry.total}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ok != QMessageBox.Yes:
            return
        summary = apply_undo(entry)
        QMessageBox.information(
            self, "Resultado",
            f"Revertidas: {summary['ok']}\n"
            f"No encontradas: {summary['missing']}\n"
            f"Conflictos: {summary['conflict']}",
        )
        # Match Esc/F-key undo: drop the entry when everything reverted cleanly
        # so a second attempt does not report spurious "missing".
        if (
            summary.get("ok", 0) > 0
            and summary.get("missing", 0) == 0
            and summary.get("conflict", 0) == 0
        ):
            self._history.delete(entry.id)
        self._reload()

    def _on_delete(self) -> None:
        entry = self._selected_entry()
        if not entry:
            return
        self._history.delete(entry.id)
        self._reload()
