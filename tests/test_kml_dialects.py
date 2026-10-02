"""KML dialect coverage for the lxml-only trace extractor.

``_extract_linestring`` used to try ``fastkml`` first and fall back to lxml.
Against fastkml 1.x that branch raised on every single document (the 0.x
``features()`` call became a list attribute), so the fallback was in fact the
only parser that ever ran — while costing 82 % of ``load_kml``. These tests pin
the dialects the dead branch claimed to handle, so removing it stays safe.
"""
from __future__ import annotations

import inspect
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.core import spatial_calculator as sc_module
from src.core.spatial_calculator import SpatialCalculator

_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'
_TRACE = "-3.71,40.417,0 -3.70,40.417,0 -3.69,40.417,0"


def _write(tmp: str, name: str, body: str) -> str:
    path = os.path.join(tmp, name)
    Path(path).write_text(body, encoding="utf-8")
    return path


class KmlDialectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _load(self, body: str, name: str = "trace.kml") -> SpatialCalculator:
        calc = SpatialCalculator()
        calc.load_kml(_write(self.tmp.name, name, body))
        return calc

    def test_linestring_nested_in_folders(self) -> None:
        calc = self._load(
            f"""{_HEADER}
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Folder><name>Tramo</name>
  <Folder><name>Eje</name><Placemark><name>traza</name>
    <LineString><coordinates>{_TRACE}</coordinates></LineString>
  </Placemark></Folder>
</Folder></Document></kml>"""
        )
        self.assertIsNotNone(calc.project_axis)
        self.assertEqual(len(list(calc.project_axis.coords)), 3)

    def test_linestring_inside_multigeometry(self) -> None:
        calc = self._load(
            f"""{_HEADER}
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
  <MultiGeometry>
    <Point><coordinates>-3.71,40.417,0</coordinates></Point>
    <LineString><coordinates>{_TRACE}</coordinates></LineString>
  </MultiGeometry>
</Placemark></Document></kml>"""
        )
        self.assertIsNotNone(calc.project_axis)
        self.assertEqual(len(list(calc.project_axis.coords)), 3)

    def test_namespaced_and_prefixed_document(self) -> None:
        calc = self._load(
            f"""{_HEADER}
<kml:kml xmlns:kml="http://www.opengis.net/kml/2.2"
         xmlns:gx="http://www.google.com/kml/ext/2.2">
  <kml:Document><kml:Placemark>
    <kml:LineString><kml:coordinates>{_TRACE}</kml:coordinates></kml:LineString>
  </kml:Placemark>
  <kml:Placemark><kml:name>PK-10+000</kml:name>
    <kml:Point><kml:coordinates>-3.71,40.417,0</kml:coordinates></kml:Point>
  </kml:Placemark></kml:Document>
</kml:kml>"""
        )
        self.assertIsNotNone(calc.project_axis)
        self.assertEqual([p.name for p in calc.named_points], ["PK-10+000"])

    def test_kmz_archive(self) -> None:
        inner = f"""{_HEADER}
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
  <LineString><coordinates>{_TRACE}</coordinates></LineString>
</Placemark></Document></kml>"""
        path = os.path.join(self.tmp.name, "trace.kmz")
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("doc.kml", inner)
        calc = SpatialCalculator()
        calc.load_kml(path)
        self.assertIsNotNone(calc.project_axis)

    def test_axis_is_synthesised_from_pk_placemarks_when_absent(self) -> None:
        calc = self._load(
            f"""{_HEADER}
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>PK-11+000</name><Point><coordinates>-3.70,40.417,0</coordinates></Point></Placemark>
  <Placemark><name>PK-10+000</name><Point><coordinates>-3.71,40.417,0</coordinates></Point></Placemark>
</Document></kml>"""
        )
        self.assertIsNotNone(calc.project_axis)
        # Joined in chainage order, not document order.
        first_lon = list(calc.project_axis.coords)[0][0]
        self.assertAlmostEqual(first_lon, -3.71)

    def test_document_without_trace_or_points_disables_pk(self) -> None:
        calc = self._load(
            f"""{_HEADER}
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>vacio</name></Document></kml>"""
        )
        self.assertIsNone(calc.project_axis)
        self.assertEqual(calc.named_points, [])
        self.assertEqual(calc.calculate_pk(40.417, -3.71), 0.0)

    def test_malformed_xml_does_not_raise(self) -> None:
        calc = self._load("<kml><Document><Placemark>truncado")
        self.assertIsNone(calc.project_axis)
        self.assertEqual(calc.named_points, [])

    def test_parser_does_not_depend_on_fastkml(self) -> None:
        """The dependency was dead weight: its only call site always raised."""
        source = inspect.getsource(sc_module)
        self.assertNotIn("fastkml", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
