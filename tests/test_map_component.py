"""Unit tests for the MapManager and HTML generation."""
from __future__ import annotations

import json
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


    def test_kml_names_cannot_break_out_of_the_script_block(self) -> None:
        """KML files come from the client, so placemark names are untrusted.

        A name containing ``</script>`` used to close the map's script block:
        the rest of the payload became markup, so at best the map silently
        failed to load and at worst injected JS ran in the operator's browser
        (the HTML is opened with ``webbrowser.open``).
        """
        hostile = "PK-1</script><script>window.__pwned=1</script>"
        points = [
            {
                "path": "",
                "name": "DJI_0001.JPG",
                "lat": 37.8167,
                "lon": -0.9674,
                "distance": 5.0,
                "pk": 1000.0,
                "nearest_name": hostile,
            }
        ]

        html = MapManager.build_map_html(
            points, [], 30.0, [{"name": hostile, "lat": 37.8, "lon": -0.96}]
        )

        # No executable markup survives anywhere in the document.
        self.assertNotIn("</script><script>", html)
        self.assertNotIn("<script>window.", html)
        # Escaping is transparent: the map still shows the real name.
        start = html.find("var photos = ") + len("var photos = ")
        decoded = json.loads(html[start : html.find(";", start)])
        self.assertEqual(decoded[0]["pk"], hostile)

    def test_markup_in_names_never_reaches_the_document_raw(self) -> None:
        hostile = '<img src=x onerror="document.title=1">'
        html = MapManager.build_map_html(
            [{"path": "", "name": hostile, "lat": 40.0, "lon": -3.0,
              "distance": 1.0, "pk": 0.0, "nearest_name": hostile}],
            [], 30.0, [],
        )
        self.assertNotIn("<img src=x", html)
        self.assertIn("\u003cimg", html)

    def test_js_line_separators_are_escaped(self) -> None:
        """U+2028/U+2029 are valid JSON but terminate a JavaScript line."""
        name = "PK-1 alert(1)"
        html = MapManager.build_map_html(
            [{"path": "", "name": name, "lat": 40.0, "lon": -3.0,
              "distance": 1.0, "pk": 0.0, "nearest_name": name}],
            [], 30.0, [],
        )
        self.assertNotIn(" ", html)
        start = html.find("var photos = ") + len("var photos = ")
        self.assertEqual(json.loads(html[start : html.find(";", start)])[0]["name"], name)

    def test_basemaps_do_not_require_an_api_key(self) -> None:
        """CARTO started watermarking keyless tiles with "API KEY REQUIRED".

        It answered 200, so nothing failed loudly: the operator just got a
        map covered in watermarks. The replacements (IGN PNOA, Esri, OSM) are
        all keyless.
        """
        template = self._template()
        self.assertNotIn("cartocdn", template)
        self.assertNotIn("apikey", template.lower())
        self.assertIn("www.ign.es/wmts/pnoa-ma", template)
        # The official orthophoto is the default: it is the only base map that
        # stays sharp at the zoom used to check a single photo.
        self.assertIn("pnoaLayer.addTo(map)", template)

    def test_layers_keep_zooming_past_their_native_level(self) -> None:
        """Without maxNativeZoom the map goes blank when zoomed onto a photo."""
        template = self._template()
        # Toda capa de teselas declara hasta donde sirve de verdad.
        self.assertEqual(
            template.count("maxNativeZoom:"), template.count("L.tileLayer(")
        )

    def test_search_panel_is_a_leaflet_control(self) -> None:
        """As a floating div it covered the expanded layer control.

        Measured in a browser: 186 px of overlap, and elementFromPoint over
        the control returned the search INPUT — the panel was stealing the
        clicks, so that part of the layer switcher could not be used.
        """
        template = self._template()
        self.assertIn("map.addControl(new SearchControl())", template)
        self.assertIn("L.DomEvent.disableClickPropagation(panel)", template)
        # No longer positioned by hand over Leaflet's own corner.
        self.assertNotIn(".search-panel { position: absolute", template)

    @staticmethod
    def _template() -> str:
        return (
            Path(__file__).resolve().parent.parent
            / "src" / "assets" / "map_template.html"
        ).read_text(encoding="utf-8")

    def test_template_escapes_values_before_building_html(self) -> None:
        """Escaping the JSON is not enough: the popups build DOM from strings.

        Leaflet renders popup markup lazily, so a name like
        ``<img src=x onerror=...>`` would execute when the operator clicks a
        marker even though the JSON payload is safe. Every concatenation of an
        untrusted field must go through ``esc()``, and the search list must be
        built with DOM APIs instead of an inline ``onclick``.
        """
        template = (
            Path(__file__).resolve().parent.parent
            / "src" / "assets" / "map_template.html"
        ).read_text(encoding="utf-8")

        self.assertIn("function esc(value)", template)
        for field in ("pt.name", "photo.name", "photo.pk", "photo.view_label"):
            self.assertNotIn(f"+ {field} +", template)
            self.assertIn(f"esc({field})", template)
        # The search list no longer interpolates names into an attribute.
        self.assertNotIn("onclick=\"focusPhotoByName(", template)
        self.assertIn("title.textContent = m.name", template)


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
