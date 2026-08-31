"""Tests for DJI orientation parsing and view classification."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

import piexif
from PIL import Image

from src.core.orientation import (
    classify_view,
    inject_jpeg_xmp_packet,
    normalize_angle_deg,
    orientation_payload,
    parse_dji_xmp,
    parse_dji_xmp_bytes,
    relative_yaw_to_axis,
    view_sort_rank,
    xmp_blob_from_pil,
)
from src.core.renamer_logic import RenamerLogic
from src.core.spatial_calculator import SpatialCalculator


def _synthetic_dji_jpeg(path: str) -> None:
    gps = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: ((37, 1), (48, 1), (0, 1)),
        piexif.GPSIFD.GPSLongitudeRef: b"W",
        piexif.GPSIFD.GPSLongitude: ((0, 1), (58, 1), (0, 1)),
    }
    exif_bytes = piexif.dump(
        {
            "0th": {
                piexif.ImageIFD.Make: b"DJI",
                piexif.ImageIFD.Model: b"FC6310",
            },
            "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:08:01 12:00:00"},
            "GPS": gps,
        }
    )
    Image.new("RGB", (64, 64), color=(10, 20, 30)).save(path, "JPEG", exif=exif_bytes)
    xmp_body = (
        b'<x:xmpmeta xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/">'
        b'<rdf:Description drone-dji:GimbalYawDegree="+100.00" '
        b'drone-dji:GimbalPitchDegree="-30.00" '
        b'drone-dji:FlightYawDegree="-169.20" '
        b'drone-dji:RelativeAltitude="+120.5"/>'
        b"</x:xmpmeta>"
    )
    overhead = b"http://ns.adobe.com/xap/1.0/\x00"
    payload = overhead + xmp_body
    segment = b"\xff\xe1" + (2 + len(payload)).to_bytes(2, "big") + payload
    assert inject_jpeg_xmp_packet(path, segment)


class OrientationTests(unittest.TestCase):
    def test_normalize_angle(self) -> None:
        self.assertAlmostEqual(normalize_angle_deg(190.0), -170.0)
        self.assertAlmostEqual(normalize_angle_deg(-190.0), 170.0)

    def test_classify_cenital_by_pitch(self) -> None:
        self.assertEqual(
            classify_view(gimbal_yaw=10.0, gimbal_pitch=-85.0, axis_bearing=0.0),
            "CEN",
        )

    def test_classify_taludes_by_relative_yaw(self) -> None:
        # Axis pointing north (0°); camera looking east (+90°) ⇒ TD.
        self.assertEqual(
            classify_view(gimbal_yaw=90.0, gimbal_pitch=-30.0, axis_bearing=0.0),
            "TD",
        )
        # Looking west (−90°) ⇒ TI.
        self.assertEqual(
            classify_view(gimbal_yaw=-90.0, gimbal_pitch=-30.0, axis_bearing=0.0),
            "TI",
        )
        # Looking along axis ⇒ TRAZA.
        self.assertEqual(
            classify_view(gimbal_yaw=5.0, gimbal_pitch=-30.0, axis_bearing=0.0),
            "TRAZA",
        )

    def test_view_sort_rank_order(self) -> None:
        self.assertLess(view_sort_rank("TI"), view_sort_rank("CEN"))
        self.assertLess(view_sort_rank("CEN"), view_sort_rank("TD"))
        self.assertLess(view_sort_rank("TD"), view_sort_rank("TRAZA"))

    def test_parse_dji_xmp_from_synthetic_jpeg(self) -> None:
        xmp = (
            b"http://ns.adobe.com/xap/1.0/\x00"
            b'<x:xmpmeta xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/">'
            b'<rdf:Description drone-dji:GimbalYawDegree="+100.00" '
            b'drone-dji:GimbalPitchDegree="-30.00" '
            b'drone-dji:FlightYawDegree="-169.20"/>'
            b"</x:xmpmeta>"
        )
        # Minimal JPEG with APP1 XMP after SOI.
        segment = b"\xff\xe1" + (2 + len(xmp)).to_bytes(2, "big") + xmp
        jpeg = b"\xff\xd8" + segment + b"\xff\xd9"
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sample.jpg")
            with open(path, "wb") as fh:
                fh.write(jpeg)
            meta = parse_dji_xmp(path)
        self.assertAlmostEqual(meta["gimbal_yaw"], 100.0)
        self.assertAlmostEqual(meta["gimbal_pitch"], -30.0)
        self.assertAlmostEqual(meta["flight_yaw"], -169.2)

    def test_parse_dji_xmp_bytes_matches_path(self) -> None:
        raw = (
            b'<x:xmpmeta xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/">'
            b'<rdf:Description drone-dji:GimbalYawDegree="+12.5" '
            b'drone-dji:GimbalPitchDegree="-80.0"/>'
            b"</x:xmpmeta>"
        )
        meta = parse_dji_xmp_bytes(raw)
        self.assertAlmostEqual(meta["gimbal_yaw"], 12.5)
        self.assertAlmostEqual(meta["gimbal_pitch"], -80.0)
        payload = orientation_payload(xmp=raw)
        self.assertAlmostEqual(payload["gimbal_yaw"], 12.5)

    def test_get_full_exif_uses_pillow_xmp_without_second_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dji.jpg")
            _synthetic_dji_jpeg(path)
            with Image.open(path) as img:
                self.assertIsNotNone(xmp_blob_from_pil(img))
            renamer = RenamerLogic(SpatialCalculator())
            payload = renamer._get_full_exif(path)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertAlmostEqual(payload["gimbal_yaw"], 100.0)
        self.assertAlmostEqual(payload["gimbal_pitch"], -30.0)
        self.assertAlmostEqual(payload["flight_yaw"], -169.2)
        self.assertAlmostEqual(payload["rel_altitude"], 120.5)
        self.assertIn("DJI", payload["camera"])

    def test_axis_bearing_east_west(self) -> None:
        calc = SpatialCalculator()
        # Horizontal axis at lat 40, lon -3.70 → -3.69 (eastward).
        path = os.path.join(tempfile.mkdtemp(), "axis.geojson")

        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[-3.70, 40.0], [-3.69, 40.0]],
                            },
                        }
                    ],
                },
                f,
            )
        calc.load_kml(path)
        bearing = calc.axis_bearing_at(40.0, -3.695)
        self.assertIsNotNone(bearing)
        # East ≈ 90°.
        self.assertAlmostEqual(bearing or 0.0, 90.0, delta=5.0)
        rel = relative_yaw_to_axis(180.0, bearing or 0.0)  # looking south
        self.assertAlmostEqual(abs(rel), 90.0, delta=5.0)


if __name__ == "__main__":
    unittest.main()
