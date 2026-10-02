"""Contract tests for the third-party behaviour the core silently relies on.

CI and the operator installers (``INSTALAR_Y_EJECUTAR.bat`` / ``ejecutar.bat``)
run ``pip install -r requirements.txt`` without a lockfile, so whatever PyPI
serves that day is what runs in the field. These tests fail loudly — and name
the assumption — instead of letting a library change surface as a confusing
``TypeError`` mid-analysis or as a silent metadata downgrade.

Each test pins an assumption that is actually made in ``src/core``.
"""
from __future__ import annotations

import unittest

import piexif
from PIL import Image
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree


class ShapelyContractTests(unittest.TestCase):
    def test_strtree_nearest_returns_an_index(self) -> None:
        """shapely >= 2.0 semantics.

        ``SpatialCalculator.find_nearest_pk_name`` does ``int(tree.nearest(p))``
        and indexes ``_points_names`` with it. On shapely 1.x ``nearest``
        returned the geometry, so ``int(...)`` raises for every photo.
        """
        tree = STRtree([Point(0, 0), Point(10, 0)])
        result = tree.nearest(Point(9, 0))
        self.assertNotIsInstance(result, Point)
        self.assertEqual(int(result), 1)

    def test_linear_referencing_round_trips(self) -> None:
        """``project``/``interpolate`` underpin every chainage calculation."""
        line = LineString([(0, 0), (100, 0), (100, 100)])
        d = line.project(Point(100, 40))
        self.assertAlmostEqual(d, 140.0)
        self.assertAlmostEqual(line.interpolate(d).y, 40.0)

    def test_distance_is_perpendicular_to_the_segment(self) -> None:
        """``corridor_distance`` is defined as distance to the axis."""
        self.assertAlmostEqual(
            LineString([(0, 0), (100, 0)]).distance(Point(50, 30)), 30.0
        )


class PiexifContractTests(unittest.TestCase):
    def test_user_comment_helper_round_trips_unicode(self) -> None:
        """``write_metadata`` degrades to raw utf-8 bytes if this import fails.

        The fallback is silent, so the EXIF comment of a whole delivery could
        change encoding without anyone noticing.
        """
        from piexif import helper

        payload = "PK-10+500-TI · ñ"
        self.assertEqual(
            helper.UserComment.load(helper.UserComment.dump(payload, encoding="unicode")),
            payload,
        )

    def test_gps_and_datetime_tags_exist(self) -> None:
        """Tag ids read during analysis."""
        for tag in (
            piexif.GPSIFD.GPSLatitude,
            piexif.GPSIFD.GPSLatitudeRef,
            piexif.GPSIFD.GPSLongitude,
            piexif.GPSIFD.GPSLongitudeRef,
        ):
            self.assertIsInstance(tag, int)
        self.assertIsInstance(piexif.ExifIFD.DateTimeOriginal, int)
        self.assertIsInstance(piexif.ImageIFD.Model, int)

    def test_insert_accepts_new_file(self) -> None:
        """Atomic EXIF writes depend on ``new_file``; without it we truncate."""
        import inspect

        self.assertIn("new_file", inspect.signature(piexif.insert).parameters)


class PillowContractTests(unittest.TestCase):
    def test_jpeg_exposes_exif_blob_and_applist(self) -> None:
        """``_get_full_exif`` reads ``info['exif']`` and scans ``applist`` once."""
        import io as _io

        exif = piexif.dump({"0th": {piexif.ImageIFD.Model: b"FC6310"}})
        buf = _io.BytesIO()
        Image.new("RGB", (8, 8)).save(buf, "JPEG", exif=exif)
        buf.seek(0)
        with Image.open(buf) as img:
            self.assertIn("exif", img.info)
            self.assertIsInstance(getattr(img, "applist", []), list)
            loaded = piexif.load(img.info["exif"])
            self.assertEqual(loaded["0th"][piexif.ImageIFD.Model], b"FC6310")

    def test_getexif_is_available(self) -> None:
        """Used by the map thumbnails and the preview pane."""
        with Image.new("RGB", (4, 4)) as img:
            self.assertTrue(hasattr(img, "getexif"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
