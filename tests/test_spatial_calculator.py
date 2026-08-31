"""Tests for the geographic accuracy of :class:`SpatialCalculator`.

These cover the local equirectangular projection that scales longitude by
``cos(lat)`` so east-west distances are not overstated at non-equatorial
latitudes (the trace and photos live around 40 deg N in Spain).
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest

from src.core.spatial_calculator import SpatialCalculator, METERS_PER_DEGREE
from src.core.renamer_logic import RenamerLogic


def _write_geojson(tmp_dir: str, geometry: dict) -> str:
    path = os.path.join(tmp_dir, "axis.geojson")
    payload = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": {}, "geometry": geometry}],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path


class SpatialAccuracyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_distance_to_axis_corrects_longitude(self) -> None:
        """A point offset purely east must use ``cos(lat)``-scaled metres."""
        lon0 = -3.7038
        axis = _write_geojson(
            self.tmp,
            {"type": "LineString", "coordinates": [[lon0, 40.4160], [lon0, 40.4180]]},
        )
        calc = SpatialCalculator()
        calc.load_kml(axis)

        # 0.001 deg east of a north-south trace centred at lat 40.4170.
        d = calc.distance_to_axis(40.4170, lon0 + 0.001)

        centroid_lat = 40.4170
        expected = 0.001 * METERS_PER_DEGREE * math.cos(math.radians(centroid_lat))

        self.assertAlmostEqual(d, expected, delta=0.5)
        # The naive flat-plane value would be ~111.3 m; the corrected one is ~85 m.
        flat = 0.001 * METERS_PER_DEGREE
        self.assertLess(d, flat - 20.0)

    def test_distance_to_axis_unaffected_north_south(self) -> None:
        """A purely north-south offset is unchanged (latitude is exact)."""
        lat0 = 40.4170
        axis = _write_geojson(
            self.tmp,
            {"type": "LineString", "coordinates": [[-3.7050, lat0], [-3.7020, lat0]]},
        )
        calc = SpatialCalculator()
        calc.load_kml(axis)

        d = calc.distance_to_axis(lat0 + 0.001, -3.7035)
        expected = 0.001 * METERS_PER_DEGREE
        self.assertAlmostEqual(d, expected, delta=0.5)

    def test_chainage_uses_metric_distance(self) -> None:
        """PK chainage along an east-west trace is the metric arc length."""
        lat0 = 40.4170
        lon_a, lon_b = -3.7050, -3.7020
        axis = _write_geojson(
            self.tmp,
            {"type": "LineString", "coordinates": [[lon_a, lat0], [lon_b, lat0]]},
        )
        calc = SpatialCalculator()
        calc.load_kml(axis)

        # No named PK points -> offset is zero, so chainage is pure geometry.
        self.assertEqual(calc.pk_offset, 0.0)
        pk = calc.calculate_pk(lat0, lon_b)

        full_len = (lon_b - lon_a) * METERS_PER_DEGREE * math.cos(math.radians(lat0))
        self.assertAlmostEqual(pk, full_len, delta=1.0)

    def test_no_axis_returns_safe_defaults(self) -> None:
        calc = SpatialCalculator()
        self.assertEqual(calc.calculate_pk(40.0, -3.7), 0.0)
        self.assertEqual(calc.distance_to_axis(40.0, -3.7), float("inf"))

    def test_find_nearest_pk_name_no_points_returns_infinite(self) -> None:
        calc = SpatialCalculator()
        name, dist = calc.find_nearest_pk_name(40.0, -3.7)
        self.assertIsNone(name)
        self.assertEqual(dist, float("inf"))

    def test_find_nearest_pk_name_picks_closest_of_many(self) -> None:
        """Spatial index (STRtree) must still return the true nearest point."""
        lat0 = 40.4170
        axis = _write_geojson(
            self.tmp,
            {"type": "LineString", "coordinates": [[-3.7100, lat0], [-3.6900, lat0]]},
        )
        calc = SpatialCalculator()
        calc.load_kml(axis)
        from src.core.models import KMLPoint

        # Scatter 50 named points along the trace plus one obvious closest.
        calc.named_points = [
            KMLPoint(name=f"PK-{i}", lat=lat0 + 0.01, lon=-3.71 + i * 0.0004) for i in range(50)
        ]
        target_lon = -3.71 + 25 * 0.0004
        calc.named_points.append(KMLPoint(name="PK-CLOSEST", lat=lat0 + 0.0001, lon=target_lon))
        calc._rebuild_metric_axis()

        name, dist = calc.find_nearest_pk_name(lat0, target_lon)
        self.assertEqual(name, "PK-CLOSEST")
        self.assertLess(dist, 1200.0)

    def test_find_nearest_pk_name_works_without_axis(self) -> None:
        """Points-only KML (no LineString) still yields sane nearest lookups."""
        from src.core.models import KMLPoint

        calc = SpatialCalculator()
        calc.named_points = [
            KMLPoint(name="PK-A", lat=40.0, lon=-3.0),
            KMLPoint(name="PK-B", lat=40.01, lon=-3.01),
        ]
        calc._rebuild_metric_axis()

        name, _dist = calc.find_nearest_pk_name(40.0001, -3.0001)
        self.assertEqual(name, "PK-A")

    def test_add_landmarks_merges_without_poisoning_pk_offset(self) -> None:
        """Extra landmarks participate in nearest-name but not in PK offset."""
        lat0 = 37.80
        lon0 = -0.96
        path = os.path.join(self.tmp, "with_pk.geojson")
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon0, lat0], [lon0, lat0 + 0.01]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {"name": "20+000"},
                    "geometry": {"type": "Point", "coordinates": [lon0, lat0]},
                },
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        calc = SpatialCalculator()
        calc.load_kml(path)
        offset_before = calc.pk_offset

        added = calc.add_landmarks_from_dicts(
            [
                {"name": "Vertedero 1", "lat": lat0 + 0.002, "lon": lon0 + 0.002},
                {"name": "Caliche", "lat": lat0 + 0.003, "lon": lon0 - 0.001},
            ]
        )
        self.assertEqual(added, 2)
        self.assertEqual(calc.pk_offset, offset_before)

        name, dist = calc.find_nearest_pk_name(lat0 + 0.002, lon0 + 0.002)
        self.assertEqual(name, "Vertedero 1")
        self.assertLess(dist, 5.0)

        # Dedup by name
        self.assertEqual(
            calc.add_landmarks_from_dicts(
                [{"name": "vertedero 1", "lat": lat0, "lon": lon0}]
            ),
            0,
        )

    def test_landmark_priority_over_closer_pk(self) -> None:
        """Within capture radius, landmarks win even if a PK is nearer."""
        lat0 = 37.80
        lon0 = -0.96
        path = os.path.join(self.tmp, "pk_vs_landmark.geojson")
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "28+700"},
                    "geometry": {"type": "Point", "coordinates": [lon0, lat0]},
                },
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

        calc = SpatialCalculator()
        calc.load_kml(path)
        calc.set_landmark_capture_radius(300.0)
        calc.add_landmarks_from_dicts(
            [{"name": "Caliche", "lat": lat0 + 0.0015, "lon": lon0 + 0.0015}]
        )

        # Photo much closer to PK than to Caliche, but still within 300 m of Caliche.
        name, dist = calc.find_nearest_pk_name(lat0 + 0.0001, lon0 + 0.0001)
        self.assertEqual(name, "Caliche")
        self.assertLess(dist, 300.0)

    def test_cluster_groups_caliche_and_palomares(self) -> None:
        """Caliche/Palomares photos share one grouped label for manual sorting."""
        calc = SpatialCalculator()
        calc.set_landmark_capture_radius(450.0)
        calc.set_landmark_groups(
            [
                {
                    "members": ["Caliche", "Palomares"],
                    "name": "Caliche-Palomares",
                    "folder": "Caliche-Palomares",
                }
            ]
        )
        calc.add_landmarks_from_dicts(
            [
                {"name": "Caliche", "lat": 37.81674183099365, "lon": -0.9674744183138699},
                {"name": "Palomares", "lat": 37.81384092347078, "lon": -0.9662552248138534},
            ]
        )
        lat, lon = 37.815165666666665, -0.9675766666666666
        name, dist = calc.find_nearest_pk_name(lat, lon)
        self.assertEqual(name, "Caliche-Palomares")
        self.assertLess(dist, 450.0)
        self.assertEqual(calc.get_landmark_folder(name), "Caliche-Palomares")

        lat_c, lon_c = 37.818042945, -0.9687013883333333
        name_c, _ = calc.find_nearest_pk_name(lat_c, lon_c)
        self.assertEqual(name_c, "Caliche-Palomares")

    def test_ensure_work_folders_creates_empty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = SpatialCalculator()
            calc.set_landmark_groups(
                [
                    {
                        "members": ["Caliche", "Palomares"],
                        "name": "Caliche-Palomares",
                        "folder": "Caliche-Palomares",
                    }
                ]
            )
            calc.add_landmarks_from_dicts(
                [
                    {"name": "Caliche", "lat": 37.8, "lon": -0.96},
                    {"name": "Palomares", "lat": 37.81, "lon": -0.96},
                    {"name": "Gregal", "lat": 37.77, "lon": -0.95},
                    {"name": "Vertedero 1", "lat": 37.79, "lon": -0.95},
                ]
            )
            logic = RenamerLogic(calc)
            logic.ensure_work_folders(tmp)
            self.assertTrue(os.path.isdir(os.path.join(tmp, "OTROS")))
            self.assertTrue(os.path.isdir(os.path.join(tmp, "VIADUCTOS")))
            self.assertTrue(os.path.isdir(os.path.join(tmp, "VERTEDEROS")))
            self.assertTrue(
                os.path.isdir(os.path.join(tmp, "VERTEDEROS", "Caliche-Palomares"))
            )
            self.assertTrue(os.path.isdir(os.path.join(tmp, "VERTEDEROS", "Gregal")))
            self.assertTrue(os.path.isdir(os.path.join(tmp, "VERTEDEROS", "Vertedero 1")))
            # Group members should not get their own folders.
            self.assertFalse(os.path.isdir(os.path.join(tmp, "VERTEDEROS", "Caliche")))

        calc = SpatialCalculator()
        self.assertEqual(calc._parse_pk_from_name("20+000"), 20000.0)
        self.assertEqual(calc._parse_pk_from_name("PK-18+653"), 18653.0)
        self.assertEqual(calc._parse_pk_from_name("18653"), 18653.0)
        self.assertIsNone(calc._parse_pk_from_name("Vertedero 1"))
        self.assertIsNone(calc._parse_pk_from_name("Caliche"))
        self.assertIsNone(calc._parse_pk_from_name("Gregal"))


class ParseKmlXmlTests(unittest.TestCase):
    """Regression tests for SpatialCalculator._parse_kml_xml (iter() fix).

    Before the fix both _extract_linestring and _extract_named_points called
    ``root.getiterator()`` which was removed in Python 3.9 and raises
    AttributeError in Python 3.9+.  The new ``_parse_kml_xml`` helper uses
    ``root.iter()`` and must be validated in isolation.
    """

    # A minimal KML fragment with a namespace prefix (the real-world trigger).
    _NAMESPACED_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>PK-5+000</name>
      <Point><coordinates>-1.234,37.567,0</coordinates></Point>
    </Placemark>
    <Placemark>
      <name>PK-6+000</name>
      <Point><coordinates>-1.235,37.568,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""

    def test_parse_kml_xml_strips_namespaces(self) -> None:
        """Tags like {http://...}Placemark become bare 'Placemark'."""
        root = SpatialCalculator._parse_kml_xml(self._NAMESPACED_KML)
        self.assertIsNotNone(root)
        placemarks = root.findall('.//Placemark')
        self.assertEqual(len(placemarks), 2)
        names = [pm.findtext('name') for pm in placemarks]
        self.assertIn("PK-5+000", names)

    def test_parse_kml_xml_returns_none_on_invalid_xml(self) -> None:
        """Corrupt XML yields None, not an exception bubble-up."""
        root = SpatialCalculator._parse_kml_xml(b"<broken xml><<<")
        self.assertIsNone(root)

    def test_parse_kml_xml_repeated_calls_are_independent(self) -> None:
        """Two successive calls must not share state (tag mutation is local)."""
        root1 = SpatialCalculator._parse_kml_xml(self._NAMESPACED_KML)
        root2 = SpatialCalculator._parse_kml_xml(self._NAMESPACED_KML)
        self.assertIsNotNone(root1)
        self.assertIsNotNone(root2)
        # Tags in root2 must still be properly stripped (not pre-stripped by root1).
        self.assertEqual(len(root2.findall('.//Placemark')), 2)

    def test_load_kml_parses_namespaced_kml_without_error(self) -> None:
        """Full load_kml round-trip on a namespaced KML extracts named points."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.kml")
            with open(path, "wb") as fh:
                fh.write(self._NAMESPACED_KML)
            calc = SpatialCalculator()
            calc.load_kml(path)
            self.assertEqual(len(calc.named_points), 2)
            names = {pt.name for pt in calc.named_points}
            self.assertIn("PK-5+000", names)
            self.assertIn("PK-6+000", names)


if __name__ == "__main__":
    unittest.main()
