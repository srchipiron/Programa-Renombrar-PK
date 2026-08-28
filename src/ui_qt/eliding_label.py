"""A ``QLabel`` that reports a long message without resizing its window.

The status bar carries the analysis summary plus the corridor coverage line —
around 300 characters after a real job. A plain ``QLabel`` asks the layout for
the full text width (3576 px measured on a 238-photo delivery), and because it
lives in the main window's status bar that becomes the window's minimum width:
the window grows itself after every analysis and can no longer be shrunk back.
On a 1920-wide laptop it ends up wider than the screen.

This label keeps the whole message available (tooltip, :meth:`text`) while
painting an elided version that fits whatever width the layout gives it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidingLabel(QLabel):
    """Show ``…`` instead of forcing the window wider."""

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(text, parent)
        self._full_text = text or ""
        # Ignored horizontally: the layout stops treating this label's text
        # width as a constraint, which is the whole point.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setTextFormat(Qt.PlainText)
        if self._full_text:
            self.setToolTip(self._full_text)

    # QLabel API -------------------------------------------------------
    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elide()

    def text(self) -> str:
        """Return the *full* message, not the elided rendering.

        Callers compose new status messages from the current one; handing them
        a truncated string with an ellipsis in the middle would corrupt it.
        """
        return self._full_text

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply_elide()

    # Internals --------------------------------------------------------
    def _apply_elide(self) -> None:
        available = max(0, self.width() - 8)
        if available <= 0:
            # Before the first layout pass there is no width to elide to;
            # showing the full text is harmless because the size policy
            # already stops it from widening anything.
            super().setText(self._full_text)
            return
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full_text, Qt.ElideRight, available))
