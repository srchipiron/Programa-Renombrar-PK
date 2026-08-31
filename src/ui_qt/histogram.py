"""Lightweight distance histogram widget.

Kept as a small Qt widget (no matplotlib) so it stays zero-dep and renders
fast inside the sidebar.  The widget accepts a list of distances and a
threshold and paints bars colored by inside/outside status.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..core.renamer_logic import histogram_axis_upper


class DistanceHistogram(QWidget):
    BINS = 24
    INSIDE_COLOR = QColor("#10b981")
    OUTSIDE_COLOR = QColor("#ef4444")
    GRID_COLOR = QColor("#1e293b")
    THRESHOLD_COLOR = QColor("#60a5fa")
    TEXT_COLOR = QColor("#94a3b8")
    #: Photos beyond the axis (take-off, another site): counted, never hidden.
    OVERFLOW_COLOR = QColor("#7c2d12")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._distances: List[float] = []
        self._threshold: float = 0.0

    def set_data(self, distances: List[float], threshold: float) -> None:
        self._distances = [float(d) for d in distances if d is not None and d != float("inf")]
        self._threshold = max(0.0, float(threshold))
        self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(28, 8, -8, -20)
        painter.fillRect(self.rect(), QColor("#0b1220"))

        painter.setPen(QPen(self.GRID_COLOR, 1))
        painter.drawRect(rect)

        if not self._distances:
            painter.setPen(self.TEXT_COLOR)
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Ejecuta un análisis para ver el histograma.")
            painter.end()
            return

        # The axis follows the decision (threshold + robust spread), not the
        # maximum: a job with photos 1.5 km off the corridor would otherwise
        # squeeze every corridor photo into the first bin.
        upper = histogram_axis_upper(self._distances, self._threshold)
        if upper <= 0:
            upper = 1.0

        bin_width = upper / self.BINS
        counts = [0] * self.BINS
        overflow = 0
        for d in self._distances:
            if d > upper:
                overflow += 1
                continue
            idx = min(int(d / bin_width), self.BINS - 1)
            counts[idx] += 1

        max_count = max(max(counts), overflow) or 1
        # The overflow bar takes the last slot so nothing is silently dropped.
        slots = self.BINS + (1 if overflow else 0)
        bar_w = rect.width() / slots

        for i, count in enumerate(counts):
            if count == 0:
                continue
            # Lower edge of bin
            low_edge = i * bin_width
            high_edge = (i + 1) * bin_width
            inside = high_edge <= self._threshold
            color = self.INSIDE_COLOR if inside else self.OUTSIDE_COLOR
            h = (count / max_count) * (rect.height() - 4)
            x = rect.left() + i * bar_w
            y = rect.bottom() - h
            painter.fillRect(int(x), int(y), int(max(1, bar_w - 1)), int(h), color)

        if overflow:
            h = (overflow / max_count) * (rect.height() - 4)
            x = rect.left() + self.BINS * bar_w
            painter.fillRect(
                int(x), int(rect.bottom() - h), int(max(1, bar_w - 1)), int(h),
                self.OVERFLOW_COLOR,
            )

        # Threshold marker
        if 0 < self._threshold < upper:
            x = rect.left() + (self._threshold / upper) * (self.BINS * bar_w)
            pen = QPen(self.THRESHOLD_COLOR, 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())

        # Labels
        painter.setPen(self.TEXT_COLOR)
        painter.setFont(QFont("system-ui", 8))
        painter.drawText(rect.left(), rect.bottom() + 14, "0")
        painter.drawText(int(rect.right() - 28), rect.bottom() + 14, f"{upper:.0f} m")
        painter.drawText(6, rect.top() + 10, f"n={len(self._distances)}")
        if overflow:
            painter.setPen(self.OVERFLOW_COLOR)
            painter.drawText(
                rect.left() + 4, rect.top() + 10, f"+{overflow} > {upper:.0f} m"
            )
        painter.end()
