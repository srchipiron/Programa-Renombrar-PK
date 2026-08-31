"""Temp files and the browser hand-off of the map tab.

Every render wrote a temp HTML and left it there for good: six orphans were
sitting in %TEMP% when this was found, and with the embedded thumbnails each
one is now megabytes rather than kilobytes.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from src.ui_qt.map_tab import MapTab  # noqa: E402


class TempFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tab = MapTab()
        self.addCleanup(self.tab.deleteLater)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_the_previous_render_is_deleted(self) -> None:
        anterior = Path(self.tmp.name) / "visor_pks_anterior.html"
        anterior.write_text("<html></html>", encoding="utf-8")
        self.tab._last_html_path = str(anterior)

        self.tab._discard_previous_html()

        self.assertFalse(anterior.exists())
        self.assertIsNone(self.tab._last_html_path)

    def test_no_previous_render_is_not_an_error(self) -> None:
        self.tab._last_html_path = None
        self.tab._discard_previous_html()  # no debe lanzar
        self.assertIsNone(self.tab._last_html_path)

    def test_an_already_deleted_file_is_not_an_error(self) -> None:
        """The operator may have cleaned %TEMP% between renders."""
        self.tab._last_html_path = str(Path(self.tmp.name) / "no_existe.html")
        self.tab._discard_previous_html()
        self.assertIsNone(self.tab._last_html_path)


class RenderTests(unittest.TestCase):
    """The main path of render_points, which nothing covered.

    An indentation slip parked the temp-file creation inside the `except`
    branch, which already returns. Every test still passed -- none of them
    called render_points -- and the map broke on the first real render with
    an UnboundLocalError.
    """

    def setUp(self) -> None:
        self.tab = MapTab()
        self.addCleanup(self.tab.deleteLater)
        self.addCleanup(self.tab._discard_previous_html)
        self.puntos = [{
            "path": "", "name": "DJI_0001.jpg", "lat": 37.8, "lon": -0.96,
            "distance": 4.2, "pk": 18100.0, "nearest_name": "PK-18+100",
        }]
        self.traza = [[37.80, -0.96], [37.81, -0.95]]

    def test_writes_a_readable_html(self) -> None:
        self.tab.render_points(self.puntos, self.traza, [], 13.8)

        self.assertIsNotNone(self.tab._last_html_path)
        escrito = Path(self.tab._last_html_path)
        self.assertTrue(escrito.exists())
        self.assertIn("DJI_0001.jpg", escrito.read_text(encoding="utf-8"))
        self.assertTrue(self.tab.open_browser_btn.isEnabled())

    def test_repeated_renders_leave_a_single_file(self) -> None:
        """Four renders used to leave four files of megabytes each."""
        vistos = []
        for _ in range(4):
            self.tab.render_points(self.puntos, self.traza, [], 13.8)
            vistos.append(Path(self.tab._last_html_path))

        self.assertEqual(len({str(p) for p in vistos}), 4)   # uno nuevo cada vez
        vivos = [p for p in vistos if p.exists()]
        self.assertEqual(vivos, [vistos[-1]])                # solo sobrevive el ultimo


class BrowserUrlTests(unittest.TestCase):
    def test_a_path_with_spaces_becomes_a_valid_url(self) -> None:
        """Built by hand, 'C:/Users/Juan Pérez/…' produced a malformed URL."""
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp) / "Juan Pérez"
            carpeta.mkdir()
            fichero = carpeta / "visor pks.html"
            fichero.write_text("<html></html>", encoding="utf-8")

            url = fichero.as_uri()

            self.assertTrue(url.startswith("file:///"))
            self.assertNotIn(" ", url)
            self.assertIn("%20", url)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
