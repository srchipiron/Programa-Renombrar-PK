"""The report an operator sends when something goes wrong.

Debugging remotely used to mean a chain of questions — which build, run from
source or installed, where are the settings, was the trace reachable, what did
the log say. One launch failure during development could never be reproduced
because none of that was recorded anywhere the operator could hand over.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.core import diagnostics, paths
from src.core.models import PhotoItem
from src.core.projects import Project
from src.core.version import __version__


class ReportTests(unittest.TestCase):
    def test_stamps_the_version_and_warns_about_the_paths(self) -> None:
        report = diagnostics.collect_diagnostics()
        self.assertIn(__version__, report)
        self.assertIn("Envíalo solo a quien te esté ayudando", report)

    def test_works_with_nothing_loaded(self) -> None:
        """A diagnostic that needs a healthy app is no use."""
        report = diagnostics.collect_diagnostics(
            config=None, project=None, analysis=None, coverage=None
        )
        self.assertIn("(ninguna seleccionada)", report)
        self.assertIn("(sin análisis en esta sesión)", report)

    def test_reports_whether_each_path_is_reachable(self) -> None:
        """"Configured" and "readable" must not look alike: these live on SMB."""
        with tempfile.TemporaryDirectory() as tmp:
            traza = Path(tmp) / "traza.kml"
            traza.write_text("x", encoding="utf-8")
            project = Project(
                name="Obra", root=tmp, kml=str(traza),
                landmark_kmls=[str(Path(tmp) / "no_existe.kml")],
            )

            report = diagnostics.collect_diagnostics(project=project)

            self.assertIn("[carpeta OK]", report)
            self.assertIn("[OK]", report)
            self.assertIn("[NO ACCESIBLE]", report)

    def test_includes_the_running_environment(self) -> None:
        report = diagnostics.collect_diagnostics(qt={"Qt": "6.11.0"})
        self.assertIn("Qt: 6.11.0", report)
        self.assertIn("Python:", report)
        self.assertIn("shapely", report)

    def test_says_where_the_settings_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths.reset_cache()
            self.addCleanup(paths.reset_cache)
            with patch.object(paths, "app_dir", return_value=Path(tmp)):
                report = diagnostics.collect_diagnostics()
            self.assertIn("portable", report)

    def test_analysis_and_coverage_are_included(self) -> None:
        class _Coverage:
            inside_count = 5
            pk_total = 10
            missing_pks = []

            def status_line(self, max_gaps=2):
                return "Cobertura PK-1+000–PK-2+000 · 5 dentro"

        report = diagnostics.collect_diagnostics(
            analysis={"fotos analizadas": 117}, coverage=_Coverage()
        )
        self.assertIn("fotos analizadas: 117", report)
        self.assertIn("5 dentro", report)


class ItemSummaryTests(unittest.TestCase):
    def test_counts_what_the_report_needs(self) -> None:
        items = [
            PhotoItem(path="a", name="a", lat=0, lon=0, is_inside_threshold=True),
            PhotoItem(path="b", name="b", lat=0, lon=0, is_inside_threshold=True, excluded=True),
            PhotoItem(path="c", name="c", lat=0, lon=0, is_inside_threshold=False),
            PhotoItem(path="d", name="d", lat=0, lon=0, is_inside_threshold=True, virtual=True),
            PhotoItem(path="e", name="e", lat=0, lon=0, is_inside_threshold=True,
                      duplicate_of="a", sidecars=["e.dng"]),
        ]

        resumen = diagnostics.summarise_items(items)

        self.assertEqual(resumen["fotos analizadas"], 5)
        # a, d y e: dentro y no excluidas. b esta excluida, c esta fuera.
        self.assertEqual(resumen["dentro del umbral"], 3)
        self.assertEqual(resumen["fuera"], 1)
        self.assertEqual(resumen["excluidas"], 1)
        self.assertEqual(resumen["fotogramas de vídeo"], 1)
        self.assertEqual(resumen["duplicadas detectadas"], 1)
        self.assertEqual(resumen["con ficheros acompañantes"], 1)

    def test_empty_analysis(self) -> None:
        self.assertEqual(diagnostics.summarise_items([])["fotos analizadas"], 0)


class WritingTests(unittest.TestCase):
    def test_filename_carries_the_timestamp(self) -> None:
        nombre = diagnostics.default_filename(datetime(2026, 8, 31, 9, 5, 1))
        self.assertEqual(nombre, "diagnostico_pks_20260831_090501.txt")

    def test_creates_the_folder_and_writes_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "nueva" / "diag.txt"
            escrito = diagnostics.write_diagnostics(destino, "cobertura ≥ 100 m · ñ")
            self.assertTrue(escrito.is_file())
            self.assertIn("≥", escrito.read_text(encoding="utf-8"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
