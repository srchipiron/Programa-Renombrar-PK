"""Real-window checks for the corridor coverage QA surfaced by MainWindow.

Boots an actual ``MainWindow`` offscreen (isolated config / session / undo
files) and drives ``_apply_preview`` with analyzed photos, so the status line
and the sidebar banner are exercised the way an operator sees them.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

import pytest

from src.core.models import PhotoItem
from src.core.spatial_calculator import METERS_PER_DEGREE

pytest.importorskip("PySide6.QtWidgets")

from src.core.config import ConfigManager  # noqa: E402
from src.ui_qt import main_window as mw  # noqa: E402
from src.ui_qt.log_handler import QtLogHandler  # noqa: E402
from src.ui_qt.session_store import SessionStore  # noqa: E402
from src.ui_qt.undo_history import UndoHistory  # noqa: E402

LAT0 = 40.4170
LON_A = -3.7100
LON_B = LON_A + (850.0 / (METERS_PER_DEGREE * math.cos(math.radians(LAT0))))


def _write_axis_geojson(tmp: Path) -> str:
    """850 m east-west axis calibrated to span PK-10+000 → PK-11+000."""
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[LON_A, LAT0], [LON_B, LAT0]],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "PK-10+000"},
                "geometry": {"type": "Point", "coordinates": [LON_A, LAT0]},
            },
            {
                "type": "Feature",
                "properties": {"name": "PK-11+000"},
                "geometry": {"type": "Point", "coordinates": [LON_B, LAT0]},
            },
        ],
    }
    path = tmp / "axis.geojson"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _photo(name: str, frac: float, pk: float) -> PhotoItem:
    """A photo sitting on the axis at ``frac`` of its length."""
    return PhotoItem(
        path=f"/jobs/{name}",
        name=name,
        lat=LAT0,
        lon=LON_A + (LON_B - LON_A) * frac,
        date_str="20260801",
        time_str="120000",
        pk_value=pk,
        distance=1.0,
        nearest_name="PK-10+000",
        is_inside_threshold=True,
    )


class MainWindowCoverageTests(unittest.TestCase):
    """The window must report trace coverage, not just holes between photos."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

        # Isolate every file the window would otherwise touch in the repo.
        self._orig_session = mw.SessionStore
        self._orig_undo = mw.UndoHistory
        mw.SessionStore = lambda *a, **k: SessionStore(root / "session.json")
        mw.UndoHistory = lambda *a, **k: UndoHistory(root / "undo.sqlite3")
        self.addCleanup(self._restore)

        cfg_path = root / "config.json"
        cfg_path.write_text(json.dumps({"threshold": 30.0, "theme": "dark"}), encoding="utf-8")
        self.window = mw.MainWindow(ConfigManager(str(cfg_path)), QtLogHandler())
        self.addCleanup(self.window.close)
        self.window.spatial_calc.load_kml(_write_axis_geojson(root))

    def _restore(self) -> None:
        mw.SessionStore = self._orig_session
        mw.UndoHistory = self._orig_undo

    def _apply(self, items) -> None:
        self.window._analysis_items = items
        self.window.sidebar.set_values(folder=self.tmp.name)
        self.window.sidebar.threshold_spin.setValue(50.0)
        self.assertTrue(self.window._apply_preview())

    def test_short_flight_is_reported_against_the_trace(self) -> None:
        # Photos only over the first ~10% of the corridor.
        self._apply([_photo(f"a{i}.jpg", i * 0.02, 10000 + i * 20) for i in range(6)])

        coverage = self.window._coverage
        self.assertIsNotNone(coverage.coverage_ratio)
        self.assertLess(coverage.coverage_ratio, 0.2)
        self.assertEqual([g.kind for g in coverage.gaps], ["final"])
        self.assertEqual([m.name for m in coverage.missing_pks], ["PK-11+000"])

        status = self.window.status_message.text()
        self.assertIn("de la traza", status)
        self.assertIn("1/2 PK con foto", status)

        hint, warns = self.window._coverage_hint()
        self.assertTrue(warns)
        self.assertIn("PK sin foto", hint)

    def test_full_coverage_reports_no_warning(self) -> None:
        items = [
            _photo(f"b{i}.jpg", i / 40.0, 10000 + i * 25) for i in range(41)
        ]
        self._apply(items)

        coverage = self.window._coverage
        self.assertAlmostEqual(coverage.coverage_ratio, 1.0, delta=0.02)
        self.assertEqual(coverage.gap_count, 0)
        self.assertEqual(coverage.missing_pks, [])

        hint, warns = self.window._coverage_hint()
        self.assertFalse(warns)
        self.assertIn("100% de la traza", hint)
        self.assertIn("sin huecos", self.window.status_message.text())

    def test_coverage_is_absent_without_a_loaded_trace(self) -> None:
        self.window.spatial_calc._reset_state()
        self._apply([_photo("c.jpg", 0.5, 10500)])
        self.assertIsNone(self.window._coverage.coverage_ratio)
        self.assertEqual(self.window._coverage_hint(), ("", False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
