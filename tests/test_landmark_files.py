"""Landmarks that live in their own file, and folder aliases.

A project keeps its landfills in a separate KML (``Vertederos.kml``) because
the client edits them between deliveries — in August 2026 they added TP-01 and
asked for that exact name. Two things blocked using it:

* ``load_kml`` resets every field, so loading the landfill file would discard
  the trace: the program could only ever hold one KML.
* A landmark named ``TP01`` produced the folder ``TP01``, and the only way to
  map a name to a different folder was a group, which demanded two members.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from src.core.spatial_calculator import SpatialCalculator

_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def _kml(placemarks: str, linestring: str = "") -> str:
    return (
        f'{_HEADER}\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"{linestring}{placemarks}</Document></kml>"
    )


def _point(name: str, lon: float, lat: float) -> str:
    return (
        f"<Placemark><name>{name}</name>"
        f"<Point><coordinates>{lon},{lat},0</coordinates></Point></Placemark>"
    )


_TRACE = (
    "<Placemark><LineString><coordinates>"
    "-0.9700,37.8000,0 -0.9600,37.8100,0"
    "</coordinates></LineString></Placemark>"
)


class LandmarkFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.trace = self.base / "traza.kml"
        self.trace.write_text(
            _kml(
                _point("PK-10+000", -0.9700, 37.8000) + _point("PK-11+000", -0.9600, 37.8100),
                _TRACE,
            ),
            encoding="utf-8",
        )
        self.calc = SpatialCalculator()
        self.calc.load_kml(str(self.trace))

    def _write(self, name: str, body: str) -> str:
        path = self.base / name
        path.write_text(body, encoding="utf-8")
        return str(path)

    def test_merging_a_landmark_file_keeps_the_trace(self) -> None:
        antes = len(self.calc.pk_placemarks())
        largo = self.calc._axis_metric.length

        added = self.calc.add_landmarks_from_kml(
            self._write("Vertederos.kml", _kml(_point("TP01", -0.9650, 37.8050)))
        )

        self.assertEqual(added, 1)
        self.assertTrue(self.calc.is_landmark_name("TP01"))
        self.assertEqual(len(self.calc.pk_placemarks()), antes)
        self.assertAlmostEqual(self.calc._axis_metric.length, largo)

    def test_chainage_posts_in_that_file_are_not_turned_into_landmarks(self) -> None:
        """Aiming it at a trace KML by mistake must not create 300 landfills."""
        added = self.calc.add_landmarks_from_kml(
            self._write(
                "confundido.kml",
                _kml(_point("PK-12+000", -0.95, 37.82) + _point("Gregal", -0.955, 37.815)),
            )
        )
        self.assertEqual(added, 1)
        self.assertTrue(self.calc.is_landmark_name("Gregal"))
        self.assertFalse(self.calc.is_landmark_name("PK-12+000"))

    def test_kmz_and_geojson_are_accepted(self) -> None:
        kmz = self.base / "vertederos.kmz"
        with zipfile.ZipFile(kmz, "w") as zf:
            zf.writestr("doc.kml", _kml(_point("Vertedero KMZ", -0.964, 37.806)))
        self.assertEqual(self.calc.add_landmarks_from_kml(str(kmz)), 1)

        geojson = self._write(
            "vertederos.geojson",
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"name": "Vertedero GeoJSON"},
                            "geometry": {"type": "Point", "coordinates": [-0.963, 37.807]},
                        }
                    ],
                }
            ),
        )
        self.assertEqual(self.calc.add_landmarks_from_kml(geojson), 1)
        self.assertTrue(self.calc.is_landmark_name("Vertedero GeoJSON"))

    def test_missing_or_unreadable_file_is_not_fatal(self) -> None:
        self.assertEqual(self.calc.add_landmarks_from_kml(str(self.base / "nope.kml")), 0)
        self.assertEqual(self.calc.add_landmarks_from_kml(""), 0)
        roto = self._write("roto.kml", "<kml><Document><Placemark>truncado")
        self.assertEqual(self.calc.add_landmarks_from_kml(roto), 0)
        # La traza sigue en pie despues de todo eso.
        self.assertEqual(len(self.calc.pk_placemarks()), 2)

    def test_merging_twice_does_not_duplicate(self) -> None:
        path = self._write("Vertederos.kml", _kml(_point("TP01", -0.9650, 37.8050)))
        self.assertEqual(self.calc.add_landmarks_from_kml(path), 1)
        self.assertEqual(self.calc.add_landmarks_from_kml(path), 0)
        self.assertEqual(
            sum(1 for pt in self.calc.named_points if pt.name == "TP01"), 1
        )


class FolderAliasTests(unittest.TestCase):
    """One-member groups: the client dictates the delivery folder name."""

    def test_single_member_group_renames_the_folder(self) -> None:
        calc = SpatialCalculator()
        calc.add_landmarks_from_dicts([{"name": "TP01", "lat": 37.80, "lon": -0.96}])
        self.assertEqual(calc.get_landmark_folder("TP01"), "TP01")

        calc.set_landmark_groups([{"members": ["TP01"], "name": "TP-01", "folder": "TP-01"}])

        self.assertEqual(calc.get_landmark_folder("TP01"), "TP-01")
        # El fotograma se etiqueta con el nombre que pide el cliente.
        name, _dist = calc.find_nearest_pk_name(37.80, -0.96)
        self.assertEqual(name, "TP-01")

    def test_multi_member_groups_still_work(self) -> None:
        calc = SpatialCalculator()
        calc.add_landmarks_from_dicts(
            [
                {"name": "Caliche", "lat": 37.81674, "lon": -0.96747},
                {"name": "Palomares", "lat": 37.81384, "lon": -0.96625},
            ]
        )
        calc.set_landmark_groups(
            [{"members": ["Caliche", "Palomares"], "name": "Caliche-Palomares",
              "folder": "Caliche-Palomares"}]
        )
        self.assertEqual(calc.get_landmark_folder("Caliche"), "Caliche-Palomares")

    def test_empty_group_is_still_rejected(self) -> None:
        calc = SpatialCalculator()
        calc.set_landmark_groups([{"members": [], "name": "vacio", "folder": "vacio"}])
        self.assertEqual(calc._landmark_groups, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
