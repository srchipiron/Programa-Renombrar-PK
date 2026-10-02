"""Cached landmark/PK partition of the point index.

``find_nearest_pk_name`` used to re-scan *every* named point per photo when any
landmark was configured (landmark sweep + non-landmark fallback), cancelling
out the STRtree. The partition is cached, so these tests pin the invalidation
rules that keep it correct when landmark membership changes after the index was
built.
"""
from __future__ import annotations

import unittest

from src.core.models import KMLPoint
from src.core.spatial_calculator import SpatialCalculator

LAT0 = 37.80
LON0 = -0.96


def _calc_with_pks(count: int = 20) -> SpatialCalculator:
    calc = SpatialCalculator()
    calc.named_points = [
        KMLPoint(name=f"PK-{i}+000", lat=LAT0 + i * 1e-3, lon=LON0) for i in range(count)
    ]
    calc._rebuild_metric_axis()
    return calc


class LandmarkPartitionTests(unittest.TestCase):
    def test_far_landmark_never_beats_a_pk_placemark(self) -> None:
        calc = _calc_with_pks()
        calc.set_landmark_capture_radius(100.0)
        # Photo sits ~264 m east of the PK line; the landmark is ~132 m further
        # east: geometrically nearest, but outside the capture radius.
        calc.add_landmarks_from_dicts(
            [{"name": "Vertedero 1", "lat": LAT0 + 5e-3, "lon": LON0 + 0.0045}]
        )
        name, dist = calc.find_nearest_pk_name(LAT0 + 5e-3, LON0 + 0.003)
        self.assertEqual(name, "PK-5+000")
        self.assertGreater(dist, 100.0)

    def test_groups_applied_after_points_still_resolve(self) -> None:
        """UI order is add_landmarks → set_landmark_groups; both must work."""
        calc = SpatialCalculator()
        calc.set_landmark_capture_radius(450.0)
        calc.add_landmarks_from_dicts(
            [
                {"name": "Caliche", "lat": 37.81674183099365, "lon": -0.9674744183138699},
                {"name": "Palomares", "lat": 37.81384092347078, "lon": -0.9662552248138534},
            ]
        )
        # Warm the partition cache before groups exist.
        calc.find_nearest_pk_name(37.815165666666665, -0.9675766666666666)
        calc.set_landmark_groups(
            [
                {
                    "members": ["Caliche", "Palomares"],
                    "name": "Caliche-Palomares",
                    "folder": "Caliche-Palomares",
                }
            ]
        )
        name, _dist = calc.find_nearest_pk_name(37.815165666666665, -0.9675766666666666)
        self.assertEqual(name, "Caliche-Palomares")

    def test_landmark_added_after_a_warm_lookup_is_seen(self) -> None:
        calc = _calc_with_pks()
        calc.set_landmark_capture_radius(300.0)
        self.assertEqual(calc.find_nearest_pk_name(LAT0 + 5e-3, LON0)[0], "PK-5+000")
        calc.add_landmarks_from_dicts(
            [{"name": "Gregal", "lat": LAT0 + 5e-3 + 1e-4, "lon": LON0 + 1e-4}]
        )
        self.assertEqual(calc.find_nearest_pk_name(LAT0 + 5e-3, LON0)[0], "Gregal")

    def test_reloading_a_kml_drops_stale_landmark_indices(self) -> None:
        calc = _calc_with_pks()
        calc.add_landmarks_from_dicts([{"name": "Gregal", "lat": LAT0, "lon": LON0}])
        calc.find_nearest_pk_name(LAT0, LON0)
        calc._reset_state()
        self.assertEqual(calc._landmark_indices, [])
        self.assertIsNone(calc._pk_tree)
        self.assertEqual(calc.find_nearest_pk_name(LAT0, LON0), (None, float("inf")))

    def test_partition_covers_every_point_exactly_once(self) -> None:
        calc = _calc_with_pks(8)
        calc.add_landmarks_from_dicts([{"name": "Vertedero 1", "lat": LAT0, "lon": LON0}])
        calc._ensure_landmark_partition()
        self.assertEqual(
            sorted(calc._landmark_indices + calc._pk_indices),
            list(range(len(calc.named_points))),
        )
        self.assertTrue(
            all(calc.is_landmark_name(calc._points_names[i]) for i in calc._landmark_indices)
        )
        self.assertFalse(
            any(calc.is_landmark_name(calc._points_names[i]) for i in calc._pk_indices)
        )

    def test_only_landmarks_present_returns_no_pk_fallback(self) -> None:
        calc = SpatialCalculator()
        calc.set_landmark_capture_radius(50.0)
        calc.add_landmarks_from_dicts([{"name": "Gregal", "lat": LAT0, "lon": LON0}])
        # Photo far outside the capture radius and no PK placemarks exist.
        name, dist = calc.find_nearest_pk_name(LAT0 + 0.05, LON0)
        self.assertIsNone(name)
        self.assertEqual(dist, float("inf"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
