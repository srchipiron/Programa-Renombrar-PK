"""Unit tests for the MapManager and HTML generation."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import piexif
from PIL import Image

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

    def test_no_source_file_calls_the_private_getexif(self) -> None:
        """Repo-wide: the private API must not come back anywhere.

        This started as a check on one method. Widening it was the lesson of
        the bug: the map was fixed and the preview pane was not, because each
        kept its own copy of the orientation code, so the pane silently
        stopped rotating PNG and TIFF. Both call core.images now, and this
        guards every file rather than the one that happened to be noticed.
        """
        import re
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent / "src"
        culpables = [
            f"{p.relative_to(raiz)}:{i}"
            for p in raiz.rglob("*.py")
            for i, linea in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            # La llamada, no la mencion en un comentario.
            if re.search(r"\w\._getexif\s*\(", linea)
        ]
        self.assertEqual(culpables, [], f"Llamada al _getexif privado en: {culpables}")

    def test_orientation_is_applied_in_one_place(self) -> None:
        import inspect

        from src.core import images

        self.assertIn("getexif", inspect.getsource(images._apply_orientation))

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


class PopupThumbnailTests(unittest.TestCase):
    """The popup used to point straight at the original photo.

    Clicking a marker decoded a 10–14 MB JPEG inside a Chromium that runs
    without the GPU. The camera's own preview is ~14 KB and reads in 28.7 ms
    per photo over the production share, concurrently.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.photo = Path(self.tmp.name) / "DJI_0001.jpg"
        buf = io.BytesIO()
        Image.new("RGB", (256, 144), (10, 120, 30)).save(buf, "JPEG")
        exif = piexif.dump({"0th": {}, "Exif": {}, "GPS": {}, "1st": {},
                            "thumbnail": buf.getvalue()})
        Image.new("RGB", (1200, 900), (30, 60, 90)).save(
            self.photo, "JPEG", exif=exif, quality=80
        )

    def _point(self, path: str) -> dict:
        return {"path": path, "name": "DJI_0001.jpg", "lat": 40.0, "lon": -3.0,
                "distance": 5.0, "pk": 1000.0, "nearest_name": "PK-1+000"}

    def test_the_payload_carries_the_embedded_preview(self) -> None:
        html = MapManager.build_map_html([self._point(str(self.photo))], [], 30.0, [])
        linea = next(l for l in html.splitlines() if l.strip().startswith("var photos = "))
        datos = json.loads(linea.strip()[len("var photos = "):].rstrip(";"))

        self.assertTrue(datos[0]["thumbnail"].startswith("data:image/jpeg;base64,"))
        # El original sigue disponible para ampliar.
        self.assertTrue(datos[0]["img_url"].startswith("file:"))

    def test_a_photo_without_a_preview_still_works(self) -> None:
        plain = Path(self.tmp.name) / "sin_thumb.jpg"
        Image.new("RGB", (400, 300)).save(plain, "JPEG")
        html = MapManager.build_map_html([self._point(str(plain))], [], 30.0, [])
        linea = next(l for l in html.splitlines() if l.strip().startswith("var photos = "))
        datos = json.loads(linea.strip()[len("var photos = "):].rstrip(";"))
        self.assertEqual(datos[0]["thumbnail"], "")
        self.assertTrue(datos[0]["img_url"])  # cae al original

    def test_a_missing_file_is_not_an_error(self) -> None:
        html = MapManager.build_map_html(
            [self._point(str(Path(self.tmp.name) / "no_existe.jpg"))], [], 30.0, []
        )
        self.assertIn("var photos = ", html)

    def test_the_template_shows_the_preview_and_zooms_the_original(self) -> None:
        template = (
            Path(__file__).resolve().parent.parent
            / "src" / "assets" / "map_template.html"
        ).read_text(encoding="utf-8")
        self.assertIn("var previewSrc = photo.thumbnail || photo.img_url", template)
        self.assertIn("openFullscreen(&#39;' + esc(fullSrc)", template)
        self.assertIn("<img src=\"' + esc(previewSrc)", template)
