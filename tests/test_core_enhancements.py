"""Tests for the new core features added in the big improvements batch.

Covers the EXIF cache, sidecar detection, duplicate detection, tolerant
EXIF datetime parsing and the rich template renderer.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.models import PhotoItem
from src.core.renamer_logic import (
    _load_cache,
    _parse_exif_datetime,
    _save_cache,
    find_sidecars,
    mark_duplicates,
    render_template,
)


class TestExifDatetime(unittest.TestCase):
    def test_canonical(self):
        self.assertEqual(_parse_exif_datetime("2026:04:21 14:23:45"), ("20260421", "142345"))

    def test_subsecond(self):
        self.assertEqual(_parse_exif_datetime("2026:04:21 14:23:45.123"), ("20260421", "142345"))

    def test_iso8601(self):
        self.assertEqual(_parse_exif_datetime("2026-04-21T14:23:45"), ("20260421", "142345"))

    def test_with_timezone_dji(self):
        self.assertEqual(_parse_exif_datetime("2026:04:21 14:23:45+02:00"), ("20260421", "142345"))

    def test_zulu_suffix(self):
        self.assertEqual(_parse_exif_datetime("2026:04:21 14:23:45Z"), ("20260421", "142345"))

    def test_invalid_returns_empty(self):
        self.assertEqual(_parse_exif_datetime(""), ("", ""))
        self.assertEqual(_parse_exif_datetime("not a date"), ("", ""))
        self.assertEqual(_parse_exif_datetime("2026:04:21"), ("", ""))


class TestSidecars(unittest.TestCase):
    def test_finds_matching_extensions(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            photo = base / "IMG_001.JPG"
            photo.write_bytes(b"jpg")
            (base / "IMG_001.DNG").write_bytes(b"dng")
            (base / "IMG_001.xmp").write_bytes(b"xmp")
            (base / "UNRELATED.TXT").write_bytes(b"x")
            (base / "IMG_002.JPG").write_bytes(b"jpg")

            found = sorted(Path(p).name.lower() for p in find_sidecars(str(photo)))
            self.assertEqual(found, ["img_001.dng", "img_001.xmp"])

    def test_empty_when_no_siblings(self):
        with TemporaryDirectory() as tmp:
            photo = Path(tmp) / "solo.jpg"
            photo.write_bytes(b"jpg")
            self.assertEqual(find_sidecars(str(photo)), [])


class TestDuplicateDetection(unittest.TestCase):
    def _make(self, name, lat=40.0, lon=-3.0, date="20260421", time="101530"):
        return PhotoItem(path=name, name=name, lat=lat, lon=lon,
                         date_str=date, time_str=time)

    def test_marks_very_close_photos_as_duplicates(self):
        items = [
            self._make("a.jpg"),
            self._make("b.jpg", time="101531"),
        ]
        flagged = mark_duplicates(items, gps_tolerance_m=5.0, time_tolerance_s=3)
        self.assertEqual(flagged, 1)
        self.assertIsNone(items[0].duplicate_of)
        self.assertEqual(items[1].duplicate_of, "a.jpg")

    def test_distant_timestamps_are_not_duplicates(self):
        items = [self._make("a.jpg"), self._make("b.jpg", time="103000")]
        flagged = mark_duplicates(items, gps_tolerance_m=5.0, time_tolerance_s=3)
        self.assertEqual(flagged, 0)

    def test_distant_gps_is_not_duplicate(self):
        items = [self._make("a.jpg"), self._make("b.jpg", lat=40.01)]
        flagged = mark_duplicates(items, gps_tolerance_m=5.0, time_tolerance_s=3)
        self.assertEqual(flagged, 0)

    def test_duplicates_across_grid_cell_boundary_are_still_found(self):
        """The bucketed search checks the 3x3 neighbourhood, so two points
        that straddle a grid cell edge (but are within tolerance) must still
        be matched."""
        from src.core.renamer_logic import METERS_PER_DEGREE

        deg_tol = 5.0 / METERS_PER_DEGREE
        # Place b just across a cell boundary from a, well within tolerance.
        items = [
            self._make("a.jpg", lat=40.0, lon=-3.0),
            self._make("b.jpg", lat=40.0 + deg_tol * 0.9, lon=-3.0, time="101531"),
        ]
        flagged = mark_duplicates(items, gps_tolerance_m=5.0, time_tolerance_s=3)
        self.assertEqual(flagged, 1)
        self.assertEqual(items[1].duplicate_of, "a.jpg")

    def test_large_batch_no_false_positives_and_runs_fast(self):
        """Many well-separated photos must not be flagged as duplicates."""
        import time

        items = [
            self._make(f"img_{i}.jpg", lat=40.0 + i * 0.001, lon=-3.0 + i * 0.001, time="101530")
            for i in range(500)
        ]
        start = time.perf_counter()
        flagged = mark_duplicates(items, gps_tolerance_m=1.0, time_tolerance_s=2)
        elapsed = time.perf_counter() - start
        self.assertEqual(flagged, 0)
        self.assertLess(elapsed, 2.0)


class TestTemplating(unittest.TestCase):
    def test_legacy_bracket_tokens(self):
        ctx = {"pk": "PK-12+034", "original": "foto_01", "date": "20260421", "time": "101530"}
        rendered = render_template("[PK]-[ORIG]-[FECHA]-[HORA]", ctx, sequence=1)
        self.assertEqual(rendered, "PK-12+034-foto_01-20260421-101530")

    def test_modern_curly_tokens_with_format(self):
        ctx = {"pk": "PK-1", "original": "x"}
        rendered = render_template("{pk}_{sequence:03d}", ctx, sequence=7)
        self.assertEqual(rendered, "PK-1_007")

    def test_unknown_token_is_preserved(self):
        rendered = render_template("{pk}_{unknown}", {"pk": "A"}, sequence=1)
        self.assertIn("{unknown}", rendered)

    def test_filesystem_unsafe_chars_are_stripped(self):
        rendered = render_template("{pk}/x:y", {"pk": "A"}, sequence=1)
        self.assertNotIn("/", rendered)
        self.assertNotIn(":", rendered)


class TestCachePersistence(unittest.TestCase):
    def test_round_trip(self):
        with TemporaryDirectory() as tmp:
            payload = {"/a/b.jpg": {"sig": [1234, 567], "exif": {"lat": 1.0}}}
            _save_cache(tmp, payload)
            restored = _load_cache(tmp)
            self.assertEqual(restored, payload)

    def test_missing_or_bad_cache_returns_empty(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(_load_cache(tmp), {})
            # Bad JSON
            (Path(tmp) / ".pk_exif_cache.json").write_text("not json", encoding="utf-8")
            self.assertEqual(_load_cache(tmp), {})


if __name__ == "__main__":
    unittest.main()
