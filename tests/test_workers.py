"""Unit tests for the Qt-side background workers."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.core.models import PhotoItem  # noqa: E402
from src.ui_qt.undo_history import UndoEntry  # noqa: E402
from src.ui_qt.workers import (  # noqa: E402
    AnalysisWorker,
    AutoThresholdWorker,
    RenameWorker,
    UndoHistoryWorker,
    UndoWorker,
)


class _Capture:
    """Collect signal payloads into plain lists for easy assertions."""

    def __init__(self, worker):
        self.progress: list[tuple[int, int, str]] = []
        self.finished: list[object] = []
        self.failed: list[str] = []
        worker.progress.connect(lambda a, b, c: self.progress.append((a, b, c)))
        worker.finished.connect(lambda payload: self.finished.append(payload))
        worker.failed.connect(lambda message: self.failed.append(message))


class TestWorkers(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Use QApplication (rather than QCoreApplication) so the same instance
        # can be reused by pytest-qt when the full test suite runs together.
        cls.app = QApplication.instance() or QApplication([])

    # ------------------------------------------------------------------
    def test_auto_threshold_worker_returns_suggestion(self) -> None:
        items = [
            PhotoItem(path=f"/tmp/{i}.jpg", name=f"{i}.jpg", lat=0.0, lon=0.0, distance=float(i))
            for i in range(1, 21)
        ]
        worker = AutoThresholdWorker(items)
        capture = _Capture(worker)
        worker.run()
        self.assertEqual(len(capture.finished), 1)
        payload = capture.finished[0]
        self.assertIsInstance(payload, dict)
        self.assertIsNotNone(payload["threshold"])
        self.assertEqual(payload["samples"], 20)
        for key in ("method", "min", "max", "mean", "median", "q1", "q3", "iqr", "p90"):
            self.assertIn(key, payload)

    def test_auto_threshold_worker_without_valid_samples(self) -> None:
        items = [PhotoItem(path="/tmp/a.jpg", name="a.jpg", lat=0.0, lon=0.0)]  # infinite distance
        worker = AutoThresholdWorker(items)
        capture = _Capture(worker)
        worker.run()
        self.assertIsNone(capture.finished[0]["threshold"])
        self.assertEqual(capture.finished[0]["samples"], 0)
        self.assertEqual(capture.finished[0]["method"], "empty")

    def test_auto_threshold_worker_ignores_extreme_outliers(self) -> None:
        # Old mean+2*stdev algo would push threshold above 1000 m on such
        # data; the new worker should return a value well inside the sane
        # topographic window and pick the strict IQR branch.
        distances = list(range(5, 20)) + [5000, 5000, 5000]
        items = [
            PhotoItem(path=f"/tmp/{i}.jpg", name=f"{i}.jpg", lat=0.0, lon=0.0, distance=float(d))
            for i, d in enumerate(distances)
        ]
        worker = AutoThresholdWorker(items)
        capture = _Capture(worker)
        worker.run()
        payload = capture.finished[0]
        self.assertLess(payload["threshold"], 100.0)
        self.assertEqual(payload["method"], "iqr_strict")

    # ------------------------------------------------------------------
    def test_analysis_worker_emits_progress_and_finished(self) -> None:
        renamer = MagicMock()
        renamer.analyze_distance_stats.return_value = {
            "min": 0.0,
            "max": 10.0,
            "mean": 5.0,
            "suggested": 15.0,
            "method": "iqr_strict",
            "items": [],
        }
        spatial = MagicMock()
        worker = AnalysisWorker("/tmp", None, spatial_calc=spatial, renamer=renamer)
        capture = _Capture(worker)
        worker.run()

        renamer.analyze_distance_stats.assert_called_once()
        spatial.load_kml.assert_not_called()
        self.assertEqual(len(capture.finished), 1)
        self.assertEqual(capture.finished[0]["suggested"], 15.0)
        self.assertFalse(capture.failed)

    def test_analysis_worker_loads_kml_when_provided(self) -> None:
        renamer = MagicMock()
        renamer.analyze_distance_stats.return_value = {"items": []}
        spatial = MagicMock()
        worker = AnalysisWorker("/tmp", "trace.kml", spatial_calc=spatial, renamer=renamer)
        worker.run()
        spatial.load_kml.assert_called_once_with("trace.kml")
        spatial.add_landmarks_from_dicts.assert_not_called()

    def test_analysis_worker_merges_extra_landmarks(self) -> None:
        renamer = MagicMock()
        renamer.analyze_distance_stats.return_value = {"items": []}
        spatial = MagicMock()
        landmarks = [{"name": "Caliche", "lat": 37.8, "lon": -0.96}]
        worker = AnalysisWorker(
            "/tmp",
            "trace.kml",
            extra_landmarks=landmarks,
            spatial_calc=spatial,
            renamer=renamer,
        )
        worker.run()
        spatial.load_kml.assert_called_once_with("trace.kml")
        spatial.add_landmarks_from_dicts.assert_called_once_with(landmarks)

    def test_analysis_worker_reports_cancellation(self) -> None:
        renamer = MagicMock()

        def _fake(folder, progress_cb=None):
            progress_cb(0, 1, "msg")
            return {"items": []}

        renamer.analyze_distance_stats.side_effect = _fake

        worker = AnalysisWorker("/tmp", None, spatial_calc=MagicMock(), renamer=renamer)
        capture = _Capture(worker)
        worker.cancel()
        worker.run()

        self.assertEqual(len(capture.finished), 1)
        self.assertEqual(capture.finished[0]["cancelled"], True)

    def test_analysis_worker_propagates_failures(self) -> None:
        renamer = MagicMock()
        renamer.analyze_distance_stats.side_effect = RuntimeError("boom")
        worker = AnalysisWorker("/tmp", None, spatial_calc=MagicMock(), renamer=renamer)
        capture = _Capture(worker)
        worker.run()
        self.assertEqual(capture.failed, ["boom"])
        self.assertFalse(capture.finished)

    # ------------------------------------------------------------------
    def test_rename_worker_invokes_core_and_forwards_stats(self) -> None:
        renamer = MagicMock()
        renamer.process_images.return_value = {"ok": 5, "errors": 0, "skipped": 1}
        worker = RenameWorker([], "/tmp", True, renamer)
        capture = _Capture(worker)
        worker.run()
        renamer.process_images.assert_called_once()
        self.assertEqual(capture.finished[0], {"ok": 5, "errors": 0, "skipped": 1})

    def test_undo_worker_returns_message(self) -> None:
        renamer = MagicMock()
        renamer.undo_last_rename_from_csv.return_value = (True, "Reverted")
        worker = UndoWorker("/tmp", renamer)
        capture = _Capture(worker)
        worker.run()
        self.assertEqual(capture.finished[0], {"ok": True, "message": "Reverted"})

    def test_undo_history_worker_reports_summary(self) -> None:
        import tempfile
        from pathlib import Path

        folder = Path(tempfile.mkdtemp())
        renamed = folder / "PK-1.jpg"
        renamed.write_bytes(b"1")
        entry = UndoEntry(
            id=1,
            timestamp=0.0,
            folder=str(folder),
            total=1,
            mapping={"PK-1.jpg": "orig.jpg"},
        )
        worker = UndoHistoryWorker(entry)
        capture = _Capture(worker)
        worker.run()
        payload = capture.finished[0]
        self.assertTrue(payload["ok"])
        self.assertIn("Revertidas: 1", payload["message"])
        self.assertTrue((folder / "orig.jpg").exists())


if __name__ == "__main__":
    unittest.main()
