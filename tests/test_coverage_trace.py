"""Trace-relative corridor coverage QA.

Gaps *between* photos never reveal a flight that stopped short of the trace,
so coverage is also measured against the corridor itself: head/tail holes, a
coverage ratio and the PK placemarks that never got a photo.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest

from src.core.coverage import (
    GAP_HEAD,
    GAP_INTERIOR,
    GAP_MIN_FLOOR_M,
    GAP_TAIL,
    compute_coverage,
    coverage_from_distances,
    suggest_gap_min,
)
from src.core.models import PhotoItem
from src.core.spatial_calculator import METERS_PER_DEGREE, SpatialCalculator


def _items(pks) -> list[PhotoItem]:
    return [
        PhotoItem(
            path=f"p{i}.jpg",
            name=f"p{i}.jpg",
            lat=0.0,
            lon=0.0,
            pk_value=float(pk),
            is_inside_threshold=True,
        )
        for i, pk in enumerate(pks)
    ]


def _calc_with_axis(tmp: str, *, pk_names=("PK-10+000", "PK-11+000")) -> SpatialCalculator:
    """East-west 850 m axis calibrated so it spans PK-10+000 → PK-11+000."""
    lat0 = 40.4170
    lon_a = -3.7100
    lon_b = lon_a + (850.0 / (METERS_PER_DEGREE * math.cos(math.radians(lat0))))
    features = [
        {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "LineString", "coordinates": [[lon_a, lat0], [lon_b, lat0]]},
        },
    ]
    for name, lon in zip(pk_names, (lon_a, lon_b)):
        features.append(
            {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {"type": "Point", "coordinates": [lon, lat0]},
            }
        )
    path = os.path.join(tmp, "axis.geojson")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    calc = SpatialCalculator()
    calc.load_kml(path)
    return calc


class TraceExtentTests(unittest.TestCase):
    def test_axis_extent_uses_calibrated_chainage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = _calc_with_axis(tmp)
            lo, hi = calc.axis_pk_extent()
            self.assertAlmostEqual(lo, 10000.0, delta=1.0)
            self.assertAlmostEqual(hi, 11000.0, delta=1.0)

    def test_extent_never_extrapolates_beyond_the_anchors(self) -> None:
        """The axis often runs past the stretch that has PK placemarks.

        Measured on a production trace (UTE Torre Pacheco): 179 anchors from
        PK-18+653 to PK-36+400 over a LineString that starts 16.7 km earlier.
        Extrapolating the calibration backwards invented a PK-1+965 and then
        reported those 16.7 km as a coverage hole, which pushed the real
        400–760 m holes down the list and dropped coverage from 57 % to 29 %.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lat0 = 40.4170
            lon_a = -3.7100
            metros = METERS_PER_DEGREE * math.cos(math.radians(lat0))
            # Eje de 2000 m; anclas solo en el tramo 850–1700 m.
            lon_fin = lon_a + 2000.0 / metros
            features = [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon_a, lat0], [lon_fin, lat0]],
                    },
                }
            ]
            for nombre, metro in (("PK-10+000", 850.0), ("PK-10+850", 1700.0)):
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"name": nombre},
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lon_a + metro / metros, lat0],
                        },
                    }
                )
            path = os.path.join(tmp, "axis.geojson")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"type": "FeatureCollection", "features": features}, fh)

            calc = SpatialCalculator()
            calc.load_kml(path)

            lo, hi = calc.axis_pk_extent()
            self.assertAlmostEqual(lo, 10000.0, delta=2.0)
            self.assertAlmostEqual(hi, 10850.0, delta=2.0)

    def test_a_flight_short_of_the_anchors_still_reports_a_head_gap(self) -> None:
        """Clamping must not hide a real hole inside the calibrated stretch."""
        report = coverage_from_distances(
            [10600, 10650, 10700], gap_min_m=100.0, trace_extent=(10000.0, 10850.0)
        )
        kinds = [g.kind for g in report.gaps]
        self.assertIn(GAP_HEAD, kinds)

    def test_extent_falls_back_to_placemarks_without_axis(self) -> None:
        calc = SpatialCalculator()
        calc.add_named_points(
            [
                type("P", (), {"name": "PK-4+000", "lat": 37.80, "lon": -0.96})(),
                type("P", (), {"name": "PK-6+000", "lat": 37.82, "lon": -0.96})(),
            ]
        )
        calc.project_axis = None
        calc._axis_metric = None
        self.assertEqual(calc.axis_pk_extent(), (4000.0, 6000.0))

    def test_no_extent_without_trace_or_pks(self) -> None:
        self.assertIsNone(SpatialCalculator().axis_pk_extent())

    def test_landmarks_are_not_pk_placemarks(self) -> None:
        calc = SpatialCalculator()
        calc.add_landmarks_from_dicts(
            [{"name": "Vertedero 1", "lat": 37.80, "lon": -0.96}]
        )
        self.assertEqual(calc.pk_placemarks(), [])


class TraceCoverageTests(unittest.TestCase):
    def test_head_and_tail_gaps_detected(self) -> None:
        report = coverage_from_distances(
            [10400, 10450, 10500], gap_min_m=100.0, trace_extent=(10000.0, 11000.0)
        )
        kinds = [g.kind for g in report.gaps]
        self.assertEqual(kinds, [GAP_HEAD, GAP_TAIL])
        self.assertEqual(report.gaps[0].length_m, 400.0)
        self.assertEqual(report.gaps[1].length_m, 500.0)
        # Each photo is credited with +-50 m of trace: 10350..10550.
        self.assertAlmostEqual(report.covered_m, 200.0)
        self.assertAlmostEqual(report.coverage_ratio, 0.2)
        self.assertIn("20%", report.status_line())

    def test_interior_gap_keeps_its_kind(self) -> None:
        report = coverage_from_distances(
            [10000, 10600, 11000], gap_min_m=100.0, trace_extent=(10000.0, 11000.0)
        )
        self.assertEqual([g.kind for g in report.gaps], [GAP_INTERIOR, GAP_INTERIOR])
        # 3 photos x 100 m of credited footprint, clipped at both trace ends.
        self.assertAlmostEqual(report.coverage_ratio, 0.2)

    def test_full_coverage_reports_one(self) -> None:
        report = coverage_from_distances(
            list(range(10000, 11001, 50)), gap_min_m=100.0, trace_extent=(10000.0, 11000.0)
        )
        self.assertEqual(report.gap_count, 0)
        self.assertAlmostEqual(report.coverage_ratio, 1.0)
        self.assertIn("100%", report.status_line())

    def test_photos_beyond_the_trace_do_not_exceed_full_coverage(self) -> None:
        # Dense flight that overshoots the trace on both ends.
        report = coverage_from_distances(
            list(range(9000, 11501, 50)),
            gap_min_m=100.0,
            trace_extent=(10000.0, 11000.0),
        )
        self.assertLessEqual(report.coverage_ratio, 1.0)
        self.assertAlmostEqual(report.coverage_ratio, 1.0)

    def test_no_photos_makes_the_whole_trace_a_gap(self) -> None:
        report = compute_coverage([], gap_min_m=100.0, trace_extent=(10000.0, 11000.0))
        self.assertEqual(report.gap_count, 1)
        self.assertEqual(report.gaps[0].length_m, 1000.0)
        self.assertAlmostEqual(report.coverage_ratio, 0.0)

    def test_without_extent_behaviour_is_unchanged(self) -> None:
        report = coverage_from_distances([10400, 10450, 10500], gap_min_m=100.0)
        self.assertEqual(report.gap_count, 0)
        self.assertIsNone(report.coverage_ratio)
        self.assertEqual(report.trace_line(), "")
        self.assertIn("sin huecos", report.status_line())

    def test_gap_label_names_the_kind(self) -> None:
        report = coverage_from_distances(
            [10500], gap_min_m=100.0, trace_extent=(10000.0, 11000.0)
        )
        labels = [g.label for g in report.gaps]
        self.assertTrue(any("inicio de traza" in label for label in labels))
        self.assertTrue(any("final de traza" in label for label in labels))


class AdaptiveGapThresholdTests(unittest.TestCase):
    """A hole is judged against the flight's own cadence, not a fixed 100 m.

    Real corridor flights shoot every 100–200 m; a fixed 100 m threshold turned
    a healthy 31 km survey into 190 "gaps" (measured on production data), which
    is indistinguishable from noise.
    """

    def test_floor_applies_without_enough_evidence(self) -> None:
        self.assertEqual(suggest_gap_min([]), GAP_MIN_FLOOR_M)
        self.assertEqual(suggest_gap_min([1000.0, 1200.0]), GAP_MIN_FLOOR_M)

    def test_scales_with_median_spacing(self) -> None:
        samples = [i * 150.0 for i in range(20)]
        self.assertAlmostEqual(suggest_gap_min(samples), 375.0)

    def test_dense_flights_keep_the_floor(self) -> None:
        samples = [i * 10.0 for i in range(20)]
        self.assertEqual(suggest_gap_min(samples), GAP_MIN_FLOOR_M)

    def test_bursts_at_one_spot_do_not_collapse_the_median(self) -> None:
        """TI/CEN/TD triplets share a PK; they are cadence noise, not spacing."""
        samples = []
        for i in range(20):
            base = i * 150.0
            samples.extend([base, base + 0.5, base + 1.0])
        self.assertAlmostEqual(suggest_gap_min(samples), 375.0, delta=5.0)

    def test_report_flags_the_threshold_as_automatic(self) -> None:
        items = _items([i * 150.0 for i in range(20)])
        report = compute_coverage(items)
        self.assertTrue(report.gap_min_auto)
        self.assertAlmostEqual(report.gap_min_m, 375.0)
        self.assertEqual(report.gap_count, 0)

    def test_explicit_threshold_is_respected(self) -> None:
        items = _items([i * 150.0 for i in range(20)])
        report = compute_coverage(items, gap_min_m=100.0)
        self.assertFalse(report.gap_min_auto)
        self.assertEqual(report.gap_count, 19)

    def test_real_anomaly_still_surfaces(self) -> None:
        pks = [i * 150.0 for i in range(10)]
        pks += [pks[-1] + 900.0 + i * 150.0 for i in range(10)]
        report = compute_coverage(_items(pks))
        self.assertEqual(report.gap_count, 1)
        self.assertAlmostEqual(report.gaps[0].length_m, 900.0)
        # The status line tells the operator the threshold was inferred.
        self.assertIn("auto", report.status_line())


class FootprintCoverageTests(unittest.TestCase):
    """Coverage credits each photo with ±tolerance of trace, not a bare point."""

    def test_sparse_flight_is_not_reported_as_zero_coverage(self) -> None:
        # One photo every 150 m over a 1 km trace, tolerance 50 m.
        report = coverage_from_distances(
            [10000 + i * 150 for i in range(7)],
            gap_min_m=1000.0,
            trace_extent=(10000.0, 11000.0),
        )
        self.assertAlmostEqual(report.covered_m, 650.0, delta=1.0)
        self.assertAlmostEqual(report.coverage_ratio, 0.65, delta=0.01)

    def test_overlapping_photos_are_not_counted_twice(self) -> None:
        report = compute_coverage(
            _items([10500.0] * 20), trace_extent=(10000.0, 11000.0)
        )
        self.assertAlmostEqual(report.covered_m, 100.0)

    def test_tolerance_widens_credited_coverage(self) -> None:
        wide = compute_coverage(
            _items([10500.0]), trace_extent=(10000.0, 11000.0), pk_tolerance_m=250.0
        )
        self.assertAlmostEqual(wide.covered_m, 500.0)


class MissingPlacemarkTests(unittest.TestCase):
    def test_flags_pk_placemarks_without_photos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = _calc_with_axis(tmp)
            report = compute_coverage(
                _items([10000.0]), gap_min_m=100.0, spatial_calc=calc
            )
            self.assertEqual(report.pk_total, 2)
            self.assertEqual([m.name for m in report.missing_pks], ["PK-11+000"])
            self.assertEqual(report.covered_pk_count, 1)
            self.assertIn("1/2 PK con foto", report.status_line())

    def test_tolerance_controls_what_counts_as_covered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = _calc_with_axis(tmp)
            near = compute_coverage(
                _items([10040.0, 11000.0]), spatial_calc=calc, pk_tolerance_m=50.0
            )
            self.assertEqual(near.missing_pks, [])
            strict = compute_coverage(
                _items([10040.0, 11000.0]), spatial_calc=calc, pk_tolerance_m=10.0
            )
            self.assertEqual([m.name for m in strict.missing_pks], ["PK-10+000"])

    def test_excluded_photos_do_not_cover_a_pk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = _calc_with_axis(tmp)
            items = _items([10000.0, 11000.0])
            items[1].excluded = True
            report = compute_coverage(items, spatial_calc=calc)
            self.assertEqual([m.name for m in report.missing_pks], ["PK-11+000"])

    def test_missing_pk_label_is_operator_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = _calc_with_axis(tmp)
            report = compute_coverage(_items([10000.0]), spatial_calc=calc)
            self.assertEqual(report.missing_pks[0].label, "PK-11+000")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
