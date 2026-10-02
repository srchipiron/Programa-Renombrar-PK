"""The status bar must never dictate the main window's width.

Measured on a real 238-photo delivery before the fix: the status label asked
the layout for 3576 px, so after every analysis the window grew itself from
1400 to 1932 px and could no longer be shrunk. On a 1920-wide laptop that is
wider than the screen.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QSizePolicy  # noqa: E402

from src.core.config import ConfigManager  # noqa: E402
from src.ui_qt import main_window as mw  # noqa: E402
from src.ui_qt.eliding_label import ElidingLabel  # noqa: E402
from src.ui_qt.log_handler import QtLogHandler  # noqa: E402
from src.ui_qt.session_store import SessionStore  # noqa: E402
from src.ui_qt.undo_history import UndoHistory  # noqa: E402

LONG_STATUS = (
    "Análisis completado: 238 fotos · umbral aplicado 19.9 m (IQR estricto "
    "(Q3 + 1.5·IQR)). 215 dentro del umbral (19.9 m) · 23 fuera · Cobertura "
    "PK-400+500–PK-431+645 · 215 dentro · 65% de la traza (PK-400+500–"
    "PK-431+834) · 205/315 PK con foto · 1 hueco(s) ≥371 m auto · "
    "PK-427+952 → PK-428+356 (404 m)"
)


class ElidingLabelTests(unittest.TestCase):
    def test_does_not_ask_the_layout_for_the_full_text_width(self) -> None:
        label = ElidingLabel(LONG_STATUS)
        self.assertEqual(
            label.sizePolicy().horizontalPolicy(), QSizePolicy.Ignored
        )

    def test_keeps_the_full_message_available(self) -> None:
        """Callers compose new messages from the current one."""
        label = ElidingLabel()
        label.setText(LONG_STATUS)
        self.assertEqual(label.text(), LONG_STATUS)
        self.assertEqual(label.toolTip(), LONG_STATUS)

    def test_paints_an_elided_version_when_narrow(self) -> None:
        label = ElidingLabel()
        label.setText(LONG_STATUS)
        label.resize(300, 20)
        painted = super(ElidingLabel, label).text()
        self.assertLess(len(painted), len(LONG_STATUS))
        self.assertTrue(painted.endswith("…"), painted[-10:])
        # …while the real message is untouched.
        self.assertEqual(label.text(), LONG_STATUS)

    def test_empty_and_short_text_are_left_alone(self) -> None:
        label = ElidingLabel()
        label.resize(400, 20)
        label.setText("Listo.")
        self.assertEqual(super(ElidingLabel, label).text(), "Listo.")
        label.setText("")
        self.assertEqual(label.text(), "")


class MainWindowWidthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self._orig = (mw.SessionStore, mw.UndoHistory)
        mw.SessionStore = lambda *a, **k: SessionStore(root / "s.json")
        mw.UndoHistory = lambda *a, **k: UndoHistory(root / "u.sqlite")
        self.addCleanup(self._restore)
        cfg = root / "config.json"
        cfg.write_text(json.dumps({"threshold": 30.0, "theme": "dark"}), encoding="utf-8")
        self.window = mw.MainWindow(ConfigManager(str(cfg)), QtLogHandler())
        self.addCleanup(self.window.close)

    def _restore(self) -> None:
        mw.SessionStore, mw.UndoHistory = self._orig

    def test_a_long_status_does_not_widen_the_window(self) -> None:
        self.window.resize(1200, 800)
        before = self.window.minimumSizeHint().width()

        self.window.status_message.setText(LONG_STATUS)

        after = self.window.minimumSizeHint().width()
        self.assertEqual(after, before)

        # Ten times longer must not move it either: the message length and the
        # window's minimum width are simply unrelated now.
        self.window.status_message.setText(LONG_STATUS * 10)
        self.assertEqual(self.window.minimumSizeHint().width(), before)
        self.assertEqual(self.window.status_message.text(), LONG_STATUS * 10)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
