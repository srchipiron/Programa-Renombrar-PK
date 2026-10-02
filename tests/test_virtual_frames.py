"""Telemetry frames imported from SRT must never reach the rename plan.

``VideoExtractor`` used to stamp every cue with ``path = <the .srt file>``.
Two things broke as a result:

1. The preview plan is a ``{path: filename}`` dict, so N frames collapsed onto
   one entry and the table showed the same proposed name on every row.
2. F7 built a rename job per frame whose source path *was* the operator's
   ``.srt``: it renamed that file to ``PK-….jpg``, failed to write EXIF into a
   text file, and rolled back — N errors per import, with the file living
   under a ``.jpg`` name in between. A failed rollback would have left the
   telemetry file renamed.

Frames still count as coverage evidence; they are just not renameable.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.core.coverage import compute_coverage
from src.core.renamer_logic import RenamerLogic
from src.core.spatial_calculator import SpatialCalculator
from src.core.video_extractor import VideoExtractor

_CUE = (
    "{n}\n00:00:0{n},000 --> 00:00:0{n},900\n"
    "[latitude: 40.4170] [longitude: -3.710{n}] [rel_alt: 120.0]\n"
)


class VirtualFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.srt = self.base / "DJI_0001.SRT"
        self.srt.write_text("\n".join(_CUE.format(n=i) for i in range(4)), encoding="utf-8")

        axis = self.base / "eje.geojson"
        axis.write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[-3.7110, 40.4170], [-3.7090, 40.4170]],
                            },
                        },
                        {
                            "type": "Feature",
                            "properties": {"name": "PK-10+000"},
                            "geometry": {"type": "Point", "coordinates": [-3.7110, 40.4170]},
                        },
                        {
                            "type": "Feature",
                            "properties": {"name": "PK-11+000"},
                            "geometry": {"type": "Point", "coordinates": [-3.7090, 40.4170]},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.calc = SpatialCalculator()
        self.calc.load_kml(str(axis))
        self.logic = RenamerLogic(self.calc)

    def _frames(self):
        items = VideoExtractor().parse_srt(str(self.srt))
        self.logic.enrich_items_spatial(items)
        self.logic.build_preview_names(items, 100.0, "[PK]-AGO26")
        return items

    def test_frames_are_flagged_and_individually_identified(self) -> None:
        items = VideoExtractor().parse_srt(str(self.srt))
        self.assertEqual(len(items), 4)
        self.assertTrue(all(it.virtual for it in items))
        self.assertEqual(len({it.path for it in items}), 4)
        self.assertEqual(len({it.name for it in items}), 4)
        # The synthetic path points at the source .srt but is not that file.
        self.assertTrue(all(it.path.startswith(str(self.srt)) for it in items))
        self.assertFalse(any(Path(it.path).is_file() for it in items))

    def test_preview_plan_has_one_row_per_frame_and_no_names(self) -> None:
        items = self._frames()
        plan = self.logic.build_preview_plan(items, str(self.base))
        self.assertEqual(plan, {})
        self.assertTrue(all(it.new_name_base == "" for it in items))
        self.assertTrue(all(it.dest_rel == "" for it in
                            self.logic.assign_destination_folders(items, str(self.base))))

    def test_frames_never_produce_rename_jobs(self) -> None:
        items = self._frames()
        self.assertEqual(self.logic._build_rename_jobs(items), [])
        self.assertEqual(self.logic.get_rename_plan(items, str(self.base))["total"], 0)

    def test_process_images_leaves_the_srt_untouched(self) -> None:
        items = self._frames()
        before = sorted(p.name for p in self.base.iterdir() if p.is_file())

        stats = self.logic.process_images(
            items, str(self.base), False, lambda *a: None, lambda: False
        )

        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["ok"], 0)
        self.assertTrue(self.srt.is_file())
        after = sorted(p.name for p in self.base.iterdir() if p.is_file())
        self.assertEqual(before, after)

    def test_frames_still_count_as_coverage_evidence(self) -> None:
        """The whole point of importing telemetry: PK evidence from video."""
        items = self._frames()
        self.assertTrue(all(it.is_inside_threshold for it in items))
        self.assertTrue(all(it.pk_display.startswith("PK-") for it in items))

        report = compute_coverage(items, spatial_calc=self.calc)
        self.assertEqual(report.inside_count, 4)
        self.assertIsNotNone(report.coverage_ratio)
        self.assertGreater(report.coverage_ratio, 0.0)

    def test_excluded_frames_behave_like_any_other_item(self) -> None:
        items = self._frames()
        items[0].excluded = True
        report = compute_coverage(items, spatial_calc=self.calc)
        self.assertEqual(report.excluded_count, 1)
        self.assertEqual(report.inside_count, 3)

    def test_session_round_trip_keeps_the_flag(self) -> None:
        """A restored session must not turn frames back into rename targets."""
        from src.ui_qt.session_store import SessionStore

        store = SessionStore(self.base / "session.json")
        store.save(str(self.base), "", self._frames())
        restored = store.load()

        self.assertIsNotNone(restored)
        self.assertEqual(len(restored["items"]), 4)
        self.assertTrue(all(it.virtual for it in restored["items"]))
        self.assertEqual(self.logic._build_rename_jobs(restored["items"]), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
