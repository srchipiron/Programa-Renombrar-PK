"""Unit tests for the MapManager and HTML generation."""
from __future__ import annotations

import unittest
from pathlib import Path

from src.map_component import MapManager


class TestMapComponent(unittest.TestCase):
    def test_build_map_html_contains_pnoa_and_telemetry(self) -> None:
        points = [
            {
                "path": "/fake/DJI_0001.JPG",
                "name": "DJI_0001.JPG",
                "lat": 37.8167,
                "lon": -0.9674,
                "distance": 12.5,
                "pk": 22600.0,
                "nearest_name": "PK 22+600",
                "gimbal_yaw": 45.0,
                "flight_yaw": 46.0,
                "rel_altitude": 112.5,
                "view_label": "TI",
            },
            {
                "path": "/fake/DJI_0002.JPG",
                "name": "DJI_0002.JPG",
                "lat": 37.8200,
                "lon": -0.9700,
                "distance": 85.0,
                "pk": 23000.0,
                "nearest_name": "PK 23+000",
                "gimbal_yaw": None,
                "flight_yaw": 90.0,
                "rel_altitude": 120.0,
                "view_label": "",
            },
        ]
        kml_coords = [[37.8160, -0.9670], [37.8210, -0.9710]]
        kml_points = [
            {"name": "PK 22+600", "lat": 37.8167, "lon": -0.9674},
            {"name": "PK 23+000", "lat": 37.8200, "lon": -0.9700},
        ]
        threshold = 30.0

        html = MapManager.build_map_html(points, kml_coords, threshold, kml_points)

        # Verificar capas oficiales y elementos de interfaz
        self.assertIn("pnoa-ma", html)
        self.assertIn("Instituto Geográfico Nacional", html)
        self.assertIn("map-search", html)
        self.assertIn("searchMap", html)
        self.assertIn("focusPhoto", html)
        self.assertIn("loading=\"lazy\"", html)
        
        # Verificar estadísticas inyectadas
        self.assertIn("2", html)  # Total 2 fotos


class TestThumbnailPublicExifApi(unittest.TestCase):
    """Regression test: MapManager must use public img.getexif(), not _getexif().

    The private _getexif() only exists on JPEG objects and was removed from the
    public Pillow surface.  The fix uses img.getexif() which works on all image
    types and returns an empty Exif object (falsy) when no EXIF is present.
    """

    def test_thumbnail_uses_public_getexif_api(self) -> None:
        """Verify the source code no longer *calls* _getexif (comments are ok)."""
        import inspect, re
        from src import map_component as mc
        source = inspect.getsource(mc.MapManager._get_base64_thumbnail)
        # Match the actual call: img._getexif() — not the substring in comments.
        calls = re.findall(r'\bimg\._getexif\s*\(', source)
        self.assertEqual(calls, [],
                         "Found a live call to img._getexif() — must use img.getexif() instead")
        self.assertIn("getexif", source,
                      "Must call img.getexif() for orientation correction")

    def test_thumbnail_on_png_without_exif_does_not_crash(self) -> None:
        """PNG images have no _getexif; the public API must handle them gracefully."""
        import io as _io
        import tempfile, os
        from PIL import Image
        from src.map_component import MapManager

        # Create a minimal 10×10 RGB PNG with no EXIF.
        img = Image.new("RGB", (10, 10), color=(100, 150, 200))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as fh:
            img.save(fh, format="PNG")
            tmp_path = fh.name
        try:
            result = MapManager._get_base64_thumbnail(tmp_path, max_size=64)
            # Result is either a data URL or empty string — must not raise.
            self.assertIsInstance(result, str)
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
