"""Tests for GeoJSON analysis export."""
from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from src.core.geojson_export import build_analysis_geojson, export_analysis_geojson
from src.core.models import PhotoItem
from src.core.spatial_calculator import METERS_PER_DEGREE, SpatialCalculator


def _item(name: str, lon: float, lat: float, pk: float, *, inside: bool = True) -> PhotoItem:
    return PhotoItem(
        path=f"/tmp/{name}",
        name=name,
        lat=lat,
        lon=lon,
        pk_value=pk,
        distance=5.0,
        nearest_name=f"PK-{int(pk // 1000)}+000",
        pk_display=f"PK-{int(pk // 1000)}+{int(pk % 1000):03d}",
        is_inside_threshold=inside,
        new_name_base=f"PK-{int(pk // 1000)}+{int(pk % 1000):03d}",
    )


def _calibrated_calc(tmp: str) -> SpatialCalculator:
    lat0 = 40.4170
    lon_a = -3.7100
    lon_b = lon_a + (850.0 / (METERS_PER_DEGREE * math.cos(math.radians(lat0))))
    path = os.path.join(tmp, "axis.geojson")
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
    calc = SpatialCalculator()
    calc.load_kml(path)
    return calc


class GeojsonExportTests(unittest.TestCase):
    def test_build_includes_photos_and_axis_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            calc = _calibrated_calc(tmp)
            items = [
                _item("a.jpg", -3.7100, 40.4170, 10000),
                _item("b.jpg", -3.7080, 40.4170, 10100),
                _item("c.jpg", -3.7040, 40.4170, 10500),
            ]
            payload = build_analysis_geojson(
                items, gap_min_m=200.0, spatial_calc=calc
            )
            self.assertEqual(payload["type"], "FeatureCollection")
            kinds = [f["properties"]["feature_kind"] for f in payload["features"]]
            self.assertEqual(kinds.count("photo"), 3)
            # One hole between photos, plus the 500 m of trace after the last
            # photo (the flight stopped short of PK-11+000).
            self.assertEqual(kinds.count("coverage_gap"), 2)
            gap_kinds = sorted(
                f["properties"]["gap_kind"]
                for f in payload["features"]
                if f["properties"]["feature_kind"] == "coverage_gap"
            )
            self.assertEqual(gap_kinds, ["final", "interior"])
            # PK-11+000 never got a photo and is flagged as such.
            missing = [
                f for f in payload["features"]
                if f["properties"]["feature_kind"] == "missing_pk"
            ]
            self.assertEqual([f["properties"]["name"] for f in missing], ["PK-11+000"])
            # Photos at 10+000/10+100/10+500 cover +-50 m each: 250 m of 1 km.
            self.assertAlmostEqual(payload["properties"]["coverage_ratio"], 0.25, delta=0.02)
            gap = next(
                f for f in payload["features"]
                if f["properties"]["feature_kind"] == "coverage_gap"
                and f["properties"]["gap_kind"] == "interior"
            )
            self.assertEqual(gap["geometry"]["type"], "LineString")
            self.assertGreaterEqual(len(gap["geometry"]["coordinates"]), 2)
            # Gap geometry must stay near the east-west corridor latitude.
            for lon, lat in gap["geometry"]["coordinates"]:
                self.assertAlmostEqual(lat, 40.4170, delta=0.002)
                self.assertTrue(-3.72 < lon < -3.70)

    def test_export_writes_utf8_file(self) -> None:
        items = [_item("solo.jpg", -0.96, 37.80, 20000)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "analisis.geojson"
            report = export_analysis_geojson(items, path, gap_min_m=100.0)
            self.assertTrue(path.is_file())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["features"]), 1)
            self.assertEqual(report.inside_count, 1)
            self.assertEqual(data["features"][0]["geometry"]["coordinates"], [-0.96, 37.80])

    def test_can_omit_outside_and_gaps(self) -> None:
        items = [
            _item("in.jpg", -3.70, 40.41, 10000, inside=True),
            _item("out.jpg", -3.60, 40.41, 12000, inside=False),
        ]
        payload = build_analysis_geojson(
            items, gap_min_m=50.0, include_outside=False, include_gaps=False
        )
        self.assertEqual(len(payload["features"]), 1)
        self.assertEqual(payload["features"][0]["properties"]["original"], "in.jpg")


if __name__ == "__main__":
    unittest.main()
