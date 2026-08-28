"""Tests for calibrated chainage, corridor distance and coverage QA."""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest

from src.core.coverage import CoverageGap, compute_coverage, coverage_from_distances
from src.core.models import PhotoItem
from src.core.renamer_logic import RenamerLogic
from src.core.spatial_calculator import SpatialCalculator, METERS_PER_DEGREE


def _write_calibrated_geojson(tmp_dir: str) -> str:
    """East-west axis with two official PK posts 1 km apart in name, ~850 m geom.

    The geometric length is shorter than the posted chainage delta (slack),
    so a single median offset cannot recover mid-span PK accurately — only
    piecewise interpolation between anchors can.
    """
    lat0 = 40.4170
    lon_a = -3.7100
    # ~850 m of geometric length at this latitude.
    lon_b = lon_a + (850.0 / (METERS_PER_DEGREE * math.cos(math.radians(lat0))))
    path = os.path.join(tmp_dir, "calibrated.geojson")
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon_a, lat0], [lon_b, lat0]],
                },
            },
            {
                "type": "Feature",
                "properties": {"name": "PK-10+000"},
                "geometry": {"type": "Point", "coordinates": [lon_a, lat0]},
            },
            {
                "type": "Feature",
                "properties": {"name": "PK-11+000"},
                "geometry": {"type": "Point", "coordinates": [lon_b, lat0]},
            },
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


class CalibratedChainageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.path = _write_calibrated_geojson(self.tmp)
        self.calc = SpatialCalculator()
        self.calc.load_kml(self.path)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_calibration_builds_two_anchors(self) -> None:
        self.assertTrue(self.calc.has_pk_calibration())
        self.assertEqual(len(self.calc._pk_calibration), 2)
        self.assertAlmostEqual(self.calc._pk_calibration[0][1], 10000.0, delta=0.1)
        self.assertAlmostEqual(self.calc._pk_calibration[1][1], 11000.0, delta=0.1)

    def test_midpoint_uses_official_interpolation_not_geom_offset(self) -> None:
        lat0 = 40.4170
        lon_a = -3.7100
        lon_b = lon_a + (850.0 / (METERS_PER_DEGREE * math.cos(math.radians(lat0))))
        mid_lon = (lon_a + lon_b) / 2.0

        pk = self.calc.calculate_pk(lat0, mid_lon)
        # Official mid-span must be ~10+500, not 10+000 + 425 m geometric.
        self.assertAlmostEqual(pk, 10500.0, delta=5.0)

        naive = self.calc._axis_metric.project(
            __import__("shapely.geometry", fromlist=["Point"]).Point(
                self.calc._to_metric(mid_lon, lat0)
            )
        ) + self.calc.pk_offset
        # Naive single-offset drifts away from official mid-span under slack.
        self.assertGreater(abs(naive - 10500.0), 50.0)

    def test_format_pk_label(self) -> None:
        self.assertEqual(SpatialCalculator.format_pk_label(10500.4), "10+500")
        self.assertEqual(SpatialCalculator.format_pk_label(10999.6), "11+000")
        self.assertEqual(SpatialCalculator.format_pk_label(-5.0), "0+000")

    def test_corridor_distance_uses_axis_not_nearest_pk(self) -> None:
        """Photo on the axis halfway between PKs is ~0 m from corridor."""
        lat0 = 40.4170
        lon_a = -3.7100
        lon_b = lon_a + (850.0 / (METERS_PER_DEGREE * math.cos(math.radians(lat0))))
        mid_lon = (lon_a + lon_b) / 2.0

        name, nearest = self.calc.find_nearest_pk_name(lat0, mid_lon)
        self.assertIsNotNone(name)
        # Nearest placemark is ~425 m away.
        self.assertGreater(nearest, 300.0)

        corridor = self.calc.corridor_distance(
            lat0, mid_lon, nearest_name=name, nearest_dist=nearest
        )
        self.assertLess(corridor, 5.0)

    def test_landmark_keeps_euclidean_corridor_distance(self) -> None:
        lat0 = 40.4170
        lon_a = -3.7100
        self.calc.set_landmark_capture_radius(500.0)
        self.calc.add_landmarks_from_dicts(
            [{"name": "Vertedero X", "lat": lat0 + 0.001, "lon": lon_a}]
        )
        name, dist = self.calc.find_nearest_pk_name(lat0 + 0.001, lon_a)
        self.assertEqual(name, "Vertedero X")
        corridor = self.calc.corridor_distance(
            lat0 + 0.001, lon_a, nearest_name=name, nearest_dist=dist
        )
        self.assertAlmostEqual(corridor, dist, delta=0.01)


class InterpolatedNamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.path = _write_calibrated_geojson(self.tmp)
        self.calc = SpatialCalculator()
        self.calc.load_kml(self.path)
        self.logic = RenamerLogic(self.calc)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preview_names_use_interpolated_chainage(self) -> None:
        item = PhotoItem(
            path=os.path.join(self.tmp, "DJI_001.JPG"),
            name="DJI_001.JPG",
            lat=40.4170,
            lon=-3.7050,
            date_str="20260826",
            time_str="120000",
            nearest_name="PK-10+000",
            nearest_dist=400.0,
            distance=2.0,
            pk_value=10500.0,
        )
        self.logic.build_preview_names([item], threshold=30.0, template="[PK]")
        self.assertTrue(item.is_inside_threshold)
        self.assertEqual(item.pk_display, "PK-10+500")
        self.assertIn("10+500", item.new_name_base)
        self.assertNotIn("10+000", item.new_name_base)

    def test_landmark_preview_keeps_landmark_name(self) -> None:
        self.calc.add_landmarks_from_dicts(
            [{"name": "Caliche", "lat": 40.42, "lon": -3.71}]
        )
        item = PhotoItem(
            path=os.path.join(self.tmp, "DJI_002.JPG"),
            name="DJI_002.JPG",
            lat=40.42,
            lon=-3.71,
            nearest_name="Caliche",
            distance=10.0,
            pk_value=10000.0,
        )
        self.logic.build_preview_names(
            [item], threshold=30.0, template="[PK]", landmark_threshold=450.0
        )
        self.assertTrue(item.is_inside_threshold)
        self.assertEqual(item.pk_display, "Caliche")
        self.assertIn("CALICHE", item.new_name_base.upper())


class CoverageReportTests(unittest.TestCase):
    def test_no_gaps_when_dense(self) -> None:
        report = coverage_from_distances([1000, 1050, 1100, 1150], gap_min_m=100.0)
        self.assertEqual(report.gap_count, 0)
        self.assertIn("sin huecos", report.status_line())

    def test_detects_gap(self) -> None:
        report = coverage_from_distances(
            [10000.0, 10100.0, 10500.0, 10600.0], gap_min_m=200.0
        )
        self.assertEqual(report.gap_count, 1)
        self.assertAlmostEqual(report.gaps[0].length_m, 400.0, delta=0.1)
        self.assertIn("1 hueco", report.status_line())

    def test_excludes_outside_threshold(self) -> None:
        items = [
            PhotoItem(
                path="a.jpg", name="a.jpg", lat=0, lon=0,
                pk_value=1000, is_inside_threshold=True,
            ),
            PhotoItem(
                path="b.jpg", name="b.jpg", lat=0, lon=0,
                pk_value=1500, is_inside_threshold=False,
            ),
            PhotoItem(
                path="c.jpg", name="c.jpg", lat=0, lon=0,
                pk_value=2000, is_inside_threshold=True,
            ),
        ]
        report = compute_coverage(items, gap_min_m=100.0)
        self.assertEqual(report.inside_count, 2)
        self.assertEqual(report.outside_count, 1)
        self.assertEqual(report.gap_count, 1)
        self.assertAlmostEqual(report.gaps[0].length_m, 1000.0, delta=0.1)

    def test_gap_label(self) -> None:
        gap = CoverageGap(start_pk_m=12000, end_pk_m=12350)
        self.assertEqual(gap.label, "PK-12+000 → PK-12+350 (350 m)")


if __name__ == "__main__":
    unittest.main()
