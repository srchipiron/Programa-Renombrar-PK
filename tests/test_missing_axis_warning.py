"""Choosing a KML with no trace must not pass unnoticed.

``calculate_pk`` answers 0.0 when there is no axis, which reads like a real
chainage: the whole delivery comes out at PK-0+000. Each client folder holds
several similarly named KML and only one carries the trace — measured on the
Torre Pacheco job, where "Vertederos.kml" sits next to "Puntos para
script.kml".
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.spatial_calculator import SpatialCalculator

SOLO_PUNTOS = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>Vertedero Gregal</name>
    <Point><coordinates>-0.96,37.80,0</coordinates></Point></Placemark>
</Document></kml>"""

CON_PK = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark><name>18+600</name>
    <Point><coordinates>-0.960,37.800,0</coordinates></Point></Placemark>
  <Placemark><name>18+700</name>
    <Point><coordinates>-0.961,37.801,0</coordinates></Point></Placemark>
  <Placemark><name>18+800</name>
    <Point><coordinates>-0.962,37.802,0</coordinates></Point></Placemark>
</Document></kml>"""


def _con_traza(etiquetas) -> str:
    """A KML carrying its own LineString plus PK placemarks on top of it.

    100 m apart in latitude (~0.0009 deg), so the labels below can either
    match the geometry or contradict it.
    """
    marcas = "".join(
        f"<Placemark><name>{etiqueta}</name><Point>"
        f"<coordinates>-0.960,{37.800 + i * 0.0009:.4f},0</coordinates>"
        f"</Point></Placemark>"
        for i, etiqueta in enumerate(etiquetas)
    )
    linea = " ".join(f"-0.960,{37.800 + i * 0.0009:.4f},0" for i in range(len(etiquetas)))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<Placemark><LineString><coordinates>{linea}</coordinates></LineString></Placemark>"
        f"{marcas}</Document></kml>"
    )


#: PK anchors along a corridor, plus a LineString drawn 20 km away: the
#: anchors project onto one end of it, exactly as in the client's survey KML.
TRAZA_APARTE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
    "<Placemark><LineString><coordinates>"
    "-1.200,38.000,0 -1.201,38.001,0"
    "</coordinates></LineString></Placemark>"
    + "".join(
        # 18+600 .. 36+600, un kilometro por ancla, como una obra de verdad.
        f"<Placemark><name>{18 + i}+600</name><Point>"
        f"<coordinates>-0.960,{37.800 + i * 0.009:.4f},0</coordinates>"
        "</Point></Placemark>"
        for i in range(19)
    )
    + "</Document></kml>"
)


def _calc(texto: str) -> SpatialCalculator:
    tmp = tempfile.NamedTemporaryFile(suffix=".kml", delete=False, mode="w", encoding="utf-8")
    tmp.write(texto)
    tmp.close()
    calc = SpatialCalculator()
    calc.load_kml(tmp.name)
    Path(tmp.name).unlink(missing_ok=True)
    return calc


class HasAxisTests(unittest.TestCase):
    def test_a_landmark_only_kml_has_no_axis(self) -> None:
        calc = _calc(SOLO_PUNTOS)
        self.assertFalse(calc.has_axis())

    def test_pk_placemarks_do_give_an_axis(self) -> None:
        """The real trace KML carries no LineString either — it is inferred."""
        calc = _calc(CON_PK)
        self.assertTrue(calc.has_axis())

    def test_a_fresh_calculator_has_no_axis(self) -> None:
        self.assertFalse(SpatialCalculator().has_axis())

    def test_without_an_axis_every_chainage_is_zero(self) -> None:
        """The behaviour the warning exists for. Documented, not endorsed."""
        calc = _calc(SOLO_PUNTOS)
        self.assertEqual(calc.calculate_pk(37.80, -0.96), 0.0)
        self.assertEqual(calc.calculate_pk(38.50, -1.50), 0.0)


class AxisSummaryTests(unittest.TestCase):
    def test_says_plainly_when_there_is_no_trace(self) -> None:
        resumen = _calc(SOLO_PUNTOS).axis_summary()
        self.assertIn("sin traza", resumen)
        self.assertIn("0", resumen)

    def test_reports_the_span_when_there_is_one(self) -> None:
        resumen = _calc(CON_PK).axis_summary()
        self.assertIn("18+600", resumen)
        self.assertIn("18+800", resumen)

    def test_the_diagnostic_carries_it(self) -> None:
        """It is the first thing asked for when someone reports a problem."""
        from src.core.diagnostics import collect_diagnostics

        class _Obra:
            name = "UTE X"
            root = ""
            kml = ""
            landmark_kmls: list = []
            threshold = 13.8
            suffix = "-AGO26"
            viaduct_pks: list = []
            extra_landmarks: list = []

        informe = collect_diagnostics(project=_Obra(), spatial=_calc(SOLO_PUNTOS))
        self.assertIn("Estado de la traza", informe)
        self.assertIn("sin traza", informe)

    def test_the_diagnostic_survives_a_broken_calculator(self) -> None:
        from src.core.diagnostics import collect_diagnostics

        class _Roto:
            def axis_summary(self):
                raise RuntimeError("boom")

        class _Obra:
            name = "UTE X"
            root = ""
            kml = ""
            landmark_kmls: list = []
            threshold = 13.8
            suffix = ""
            viaduct_pks: list = []
            extra_landmarks: list = []

        informe = collect_diagnostics(project=_Obra(), spatial=_Roto())
        self.assertIn("no se pudo determinar", informe)


class CalibrationResidualTests(unittest.TestCase):
    """An axis can load and still be the wrong geometry.

    That case is worse than no axis: the chainage looks plausible and is
    wrong. Measured on the real job — the trace KML reproduces its own 180
    anchors to 0.00 m; the client's survey KML in the same folder, whose
    geometry is drawing rather than a centreline, is out by 18 553 m.
    """

    def test_a_real_trace_reproduces_its_own_anchors(self) -> None:
        calc = _calc(_con_traza(["18+600", "18+700", "18+800", "18+900"]))
        self.assertLess(calc.calibration_residual_m(), 5.0)
        self.assertTrue(calc.axis_looks_trustworthy())

    def test_an_axis_that_does_not_run_along_the_anchors_is_caught(self) -> None:
        """The shape of the real failure.

        The client's survey KML holds 123 401 LineStrings and the loader takes
        the first, so the axis is a scrap of drawing geometry kilometres from
        the chainage anchors. They all project onto one end of it and come
        back as PK 0.
        """
        calc = _calc(TRAZA_APARTE)
        self.assertTrue(calc.has_axis())          # el eje carga igual
        self.assertGreater(
            calc.calibration_residual_m(), SpatialCalculator.CALIBRATION_TOLERANCE_M
        )
        self.assertFalse(calc.axis_looks_trustworthy())

    def test_an_inferred_axis_gets_no_verdict_rather_than_a_fake_pass(self) -> None:
        """Joining the anchors reproduces them however wrong their labels are.

        Reporting 0.00 m there would claim a verification that did not happen.
        """
        calc = _calc(CON_PK)
        self.assertTrue(calc.has_axis())
        self.assertIsNone(calc.calibration_residual_m())
        self.assertTrue(calc.axis_looks_trustworthy())
        self.assertIn("deducida de los PK", calc.axis_summary())

    def test_no_anchors_means_no_verdict_not_a_false_alarm(self) -> None:
        calc = _calc(SOLO_PUNTOS)
        self.assertIsNone(calc.calibration_residual_m())
        self.assertTrue(calc.axis_looks_trustworthy())

    def test_the_summary_flags_an_untrustworthy_trace(self) -> None:
        resumen = _calc(TRAZA_APARTE).axis_summary()
        self.assertIn("NO FIABLE", resumen)
        self.assertIn("geometría propia", resumen)

    def test_the_summary_does_not_cry_wolf(self) -> None:
        resumen = _calc(_con_traza(["18+600", "18+700", "18+800", "18+900"])).axis_summary()
        self.assertNotIn("NO FIABLE", resumen)


class OperatorWarningTests(unittest.TestCase):
    """The verdict has to reach the person, not just the log."""

    def setUp(self) -> None:
        import pytest

        pytest.importorskip("PySide6.QtWidgets")

    def _avisos(self, result: dict):
        from unittest.mock import patch

        from src.ui_qt.main_window import MainWindow

        vistos = []
        with patch.object(MainWindow, "_error", lambda self, msg: vistos.append(msg)):
            MainWindow._warn_about_the_trace(
                MainWindow.__new__(MainWindow), result, "C:/obra/Vertederos.kml"
            )
        return vistos

    def test_no_trace_is_reported(self) -> None:
        avisos = self._avisos({"kml_has_axis": False})
        self.assertEqual(len(avisos), 1)
        self.assertIn("PK-0+000", avisos[0])
        self.assertIn("Vertederos.kml", avisos[0])

    def test_an_untrustworthy_trace_is_reported_with_its_error(self) -> None:
        avisos = self._avisos(
            {"kml_has_axis": True, "kml_axis_trustworthy": False,
             "kml_axis_residual_m": 18553.0}
        )
        self.assertEqual(len(avisos), 1)
        self.assertIn("18553 m", avisos[0])

    def test_a_healthy_trace_says_nothing(self) -> None:
        self.assertEqual(
            self._avisos({"kml_has_axis": True, "kml_axis_trustworthy": True}), []
        )

    def test_an_analysis_without_a_kml_says_nothing(self) -> None:
        """No KML chosen is not a trace problem."""
        self.assertEqual(self._avisos({"items": []}), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
