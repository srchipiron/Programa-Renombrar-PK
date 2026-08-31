"""Tests for analysis-folder pruning, path confinement, SRT GPS and lon-scale duplicates."""
from __future__ import annotations

import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from src.core.models import PhotoItem
from src.core.renamer_logic import (
    METERS_PER_DEGREE,
    RenamerLogic,
    collect_analysis_image_files,
    is_analysis_skip_dir,
    mark_duplicates,
    safe_join_under,
)
from src.core.video_extractor import (
    VideoExtractor,
    extract_gps_from_srt_text,
    extract_wall_clock,
)


def _touch_jpeg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color=(10, 20, 30)).save(path, format="JPEG")


class TestAnalysisSkipDirs(unittest.TestCase):
    def test_skip_names_are_case_insensitive(self) -> None:
        self.assertTrue(is_analysis_skip_dir("_backup_originales"))
        self.assertTrue(is_analysis_skip_dir("VIADUCTOS"))
        self.assertTrue(is_analysis_skip_dir("Vertederos"))
        self.assertTrue(is_analysis_skip_dir("otros"))
        self.assertFalse(is_analysis_skip_dir("vuelo_01"))
        self.assertFalse(is_analysis_skip_dir("PK-12+000"))

    def test_collect_skips_backup_and_work_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / "brutos" / "DJI_001.JPG"
            _touch_jpeg(keep)
            _touch_jpeg(root / "_backup_originales" / "DJI_OLD.JPG")
            _touch_jpeg(root / "VIADUCTOS" / "PK-1+000_TI.JPG")
            _touch_jpeg(root / "VERTEDEROS" / "Caliche" / "old.JPG")
            _touch_jpeg(root / "OTROS" / "misc.JPG")
            # Nested day folder must still be walked.
            nested = root / "dia_02" / "DJI_002.JPG"
            _touch_jpeg(nested)

            found = {Path(p).name for p in collect_analysis_image_files(str(root))}
            self.assertEqual(found, {"DJI_001.JPG", "DJI_002.JPG"})

    def test_analyze_does_not_ingest_backup_photos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "live.jpg"
            _touch_jpeg(live)
            _touch_jpeg(root / "_backup_originales" / "backup.jpg")

            spatial = mock.Mock()
            spatial.find_nearest_pk_name.return_value = ("PK-1+000", 5.0)
            spatial.corridor_distance.return_value = 5.0
            spatial.calculate_pk.return_value = 1000.0
            spatial.axis_bearing_at.return_value = 90.0
            spatial.project_axis = None

            logic = RenamerLogic(spatial, max_workers=1)
            with mock.patch.object(
                logic,
                "_get_full_exif",
                return_value={
                    "lat": 40.0,
                    "lon": -3.0,
                    "date": "20260801",
                    "time": "120000",
                    "camera": "Test",
                },
            ):
                stats = logic.analyze_distance_stats(str(root), use_cache=False)

            names = [it.name for it in stats["items"]]
            self.assertEqual(names, ["live.jpg"])
            self.assertEqual(spatial.find_nearest_pk_name.call_count, 1)


class TestSafeJoinUnder(unittest.TestCase):
    def test_accepts_simple_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            joined = safe_join_under(tmp, "VERTEDEROS", "Caliche")
            self.assertIsNotNone(joined)
            self.assertTrue(joined.startswith(os.path.abspath(tmp)))
            self.assertTrue(joined.endswith(os.path.join("VERTEDEROS", "Caliche")))

    def test_rejects_parent_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(safe_join_under(tmp, "..", "outside"))
            self.assertIsNone(safe_join_under(tmp, "VERTEDEROS/../../evil"))
            self.assertIsNone(safe_join_under(tmp, "C:\\Windows"))
            self.assertIsNone(safe_join_under(tmp, "/etc/passwd"))

    def test_ensure_work_folders_skips_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spatial = mock.Mock()
            spatial._landmark_groups = [
                {"name": "evil", "folder": "../../outside_escape", "members": []},
                {"name": "ok", "folder": "Caliche-Palomares", "members": []},
            ]
            spatial._landmark_names = set()
            spatial.named_points = []
            logic = RenamerLogic(spatial)
            created = logic.ensure_work_folders(tmp)
            abs_created = {os.path.abspath(p) for p in created}
            self.assertTrue(any(p.endswith(os.path.join("VERTEDEROS", "Caliche-Palomares")) for p in abs_created))
            self.assertFalse(any("outside_escape" in p for p in abs_created))


class TestDuplicateLongitudeScale(unittest.TestCase):
    def test_lon_tolerance_accounts_for_latitude(self) -> None:
        """At 40°N, 1 m east is ~lon_tol degrees; using lat_tol alone is wrong."""
        lat = 40.0
        cos_lat = abs(math.cos(math.radians(lat)))
        lon_tol_1m = 1.0 / (METERS_PER_DEGREE * cos_lat)
        # Place b ~0.9 m east — must be a duplicate with 1 m tolerance.
        a = PhotoItem(path="a.jpg", name="a.jpg", lat=lat, lon=-3.0,
                      date_str="20260801", time_str="120000")
        b = PhotoItem(path="b.jpg", name="b.jpg", lat=lat, lon=-3.0 + lon_tol_1m * 0.9,
                      date_str="20260801", time_str="120001")
        flagged = mark_duplicates([a, b], gps_tolerance_m=1.0, time_tolerance_s=2)
        self.assertEqual(flagged, 1)
        self.assertEqual(b.duplicate_of, "a.jpg")

    def test_far_east_not_duplicate_when_scaled(self) -> None:
        lat = 40.0
        cos_lat = abs(math.cos(math.radians(lat)))
        lon_tol_1m = 1.0 / (METERS_PER_DEGREE * cos_lat)
        a = PhotoItem(path="a.jpg", name="a.jpg", lat=lat, lon=-3.0,
                      date_str="20260801", time_str="120000")
        b = PhotoItem(
            path="b.jpg",
            name="b.jpg",
            lat=lat,
            lon=-3.0 + lon_tol_1m * 1.5,  # ~1.5 m east → outside 1 m
            date_str="20260801",
            time_str="120001",
        )
        flagged = mark_duplicates([a, b], gps_tolerance_m=1.0, time_tolerance_s=2)
        self.assertEqual(flagged, 0)


class TestSrtGpsParsing(unittest.TestCase):
    def test_bracket_format(self) -> None:
        text = "[latitude: 59.302335] [longitude: 18.203059] [rel_alt: 10.2 abs_alt: 142.7]"
        lat, lon, alt = extract_gps_from_srt_text(text)
        self.assertAlmostEqual(lat, 59.302335)
        self.assertAlmostEqual(lon, 18.203059)
        self.assertAlmostEqual(alt, 10.2)

    def test_gps_function_format(self) -> None:
        text = "GPS(39.906217,116.391305,69.800) BAROMETER(91.2) HOME(39.9,116.4)"
        lat, lon, alt = extract_gps_from_srt_text(text)
        self.assertAlmostEqual(lat, 39.906217)
        self.assertAlmostEqual(lon, 116.391305)
        self.assertAlmostEqual(alt, 69.8)

    def test_gps_with_unit_suffix_and_space(self) -> None:
        text = "GPS (36.6146, -6.1120, 0.0M) BAROMETER:0.3M"
        lat, lon, alt = extract_gps_from_srt_text(text)
        self.assertAlmostEqual(lat, 36.6146)
        self.assertAlmostEqual(lon, -6.1120)
        self.assertAlmostEqual(alt, 0.0)

    def test_wall_clock(self) -> None:
        date, time = extract_wall_clock("FrameCnt: 1\n2024-01-15 14:30:22,123\n[latitude: 1.0]")
        self.assertEqual(date, "20240115")
        self.assertEqual(time, "143022")

    def test_parse_srt_file_end_to_end(self) -> None:
        body = """1
00:00:00,000 --> 00:00:00,033
GPS(40.4168,-3.7038,120.5)

2
00:00:00,033 --> 00:00:00,066
[latitude: 40.4170] [longitude: -3.7040] [rel_alt: 121.0]

3
00:00:00,066 --> 00:00:00,100
no gps here
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "flight.SRT"
            path.write_text(body, encoding="utf-8")
            items = VideoExtractor().parse_srt(str(path))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].time_str, "000000")
        self.assertAlmostEqual(items[0].lat, 40.4168)
        self.assertAlmostEqual(items[1].rel_altitude or 0.0, 121.0)

    def test_enrich_items_spatial_fills_pk(self) -> None:
        spatial = mock.Mock()
        spatial.find_nearest_pk_name.return_value = ("PK-2+500", 12.0)
        spatial.corridor_distance.return_value = 8.5
        spatial.calculate_pk.return_value = 2500.0
        spatial.axis_bearing_at.return_value = 45.0
        logic = RenamerLogic(spatial)
        items = [
            PhotoItem(path="x.srt", name="Frame_000000.jpg", lat=40.0, lon=-3.0),
        ]
        logic.enrich_items_spatial(items)
        self.assertEqual(items[0].nearest_name, "PK-2+500")
        self.assertEqual(items[0].distance, 8.5)
        self.assertEqual(items[0].pk_value, 2500.0)


class TestDestinationPreview(unittest.TestCase):
    def test_assign_destination_viaductos_and_root(self) -> None:
        spatial = mock.Mock()
        spatial.get_landmark_folder.return_value = None
        spatial.is_landmark_name.return_value = False
        logic = RenamerLogic(spatial)
        logic.set_viaduct_pks(["12+000"])

        with tempfile.TemporaryDirectory() as tmp:
            viaduct = PhotoItem(
                path=os.path.join(tmp, "a.jpg"),
                name="a.jpg",
                lat=40.0,
                lon=-3.0,
                nearest_name="PK-12+000",
                is_inside_threshold=True,
                new_name_base="PK-12+000",
                view_label="CEN",
            )
            root_item = PhotoItem(
                path=os.path.join(tmp, "b.jpg"),
                name="b.jpg",
                lat=40.0,
                lon=-3.0,
                nearest_name="PK-1+000",
                is_inside_threshold=True,
                new_name_base="PK-1+000",
                view_label="TRAZA",
            )
            outside = PhotoItem(
                path=os.path.join(tmp, "c.jpg"),
                name="c.jpg",
                lat=40.0,
                lon=-3.0,
                is_inside_threshold=False,
                new_name_base="",
            )
            logic.assign_destination_folders([viaduct, root_item, outside], tmp)
            self.assertEqual(viaduct.dest_rel, "VIADUCTOS")
            self.assertEqual(root_item.dest_rel, "(raíz)")
            self.assertEqual(outside.dest_rel, "")

            plan = logic.build_preview_plan([viaduct, root_item], tmp)
            # Final filename only — destination lives in dest_rel / Destino column.
            self.assertEqual(plan[viaduct.path], "PK-12+000.jpg")
            self.assertEqual(plan[root_item.path], "PK-1+000.jpg")


if __name__ == "__main__":
    unittest.main()
