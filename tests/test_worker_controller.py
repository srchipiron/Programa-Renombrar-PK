"""Unit tests for WorkerController busy gate."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ui_qt.worker_controller import WorkerController
from src.ui_qt.workers import _BaseWorker


class _DummyWorker(_BaseWorker):
    def run(self) -> None:
        self.finished.emit({"ok": True})


class TestWorkerController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_rejects_second_start_while_busy(self) -> None:
        started: list[str] = []
        cleared: list[int] = []
        ctl = WorkerController(
            on_started=lambda msg: started.append(msg),
            on_cleared=lambda: cleared.append(1),
        )
        w1 = _DummyWorker()
        w2 = _DummyWorker()
        self.assertTrue(ctl.start(w1, "uno"))
        self.assertTrue(ctl.busy)
        self.assertFalse(ctl.start(w2, "dos"))
        self.assertEqual(started, ["uno"])
        ctl.clear()
        self.assertFalse(ctl.busy)
        self.assertEqual(cleared, [1])
        self.assertTrue(ctl.start(w2, "dos"))
        self.assertEqual(started, ["uno", "dos"])

    def test_cancel_idle_returns_false(self) -> None:
        ctl = WorkerController()
        self.assertFalse(ctl.cancel())


if __name__ == "__main__":
    unittest.main()
