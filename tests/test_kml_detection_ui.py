"""KML recognition, driven through a real MainWindow.

Choosing the wrong KML out of three similarly named ones put a whole delivery
at PK-0+000. The window now recognises the right one from the folder and says
what it did.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from src.core.config import ConfigManager  # noqa: E402
from src.core.kml_profile import discover_kmls, recommend  # noqa: E402
from src.ui_qt import main_window as mw  # noqa: E402
from src.ui_qt.log_handler import QtLogHandler  # noqa: E402
from src.ui_qt.session_store import SessionStore  # noqa: E402
from src.ui_qt.undo_history import UndoHistory  # noqa: E402

from tests.test_kml_profile import (  # noqa: E402
    LANDMARKS_KML,
    SURVEY_KML,
    trace_kml,
    trace_with_landfills,
)


class KmlDetectionWindowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        self.obra = self.base / "CLIENTES" / "UTE EJEMPLO"
        self.mes = self.obra / "2026" / "8.Agosto"
        self.mes.mkdir(parents=True)
        self.traza = self.obra / "Puntos.kml"
        self.vertederos = self.obra / "Vertederos.kml"
        self.traza.write_text(trace_kml(), encoding="utf-8")
        self.vertederos.write_text(LANDMARKS_KML, encoding="utf-8")
        (self.obra / "Parcela.kml").write_text(SURVEY_KML, encoding="utf-8")

        self._orig = (mw.SessionStore, mw.UndoHistory)
        mw.SessionStore = lambda *a, **k: SessionStore(self.base / "s.json")
        mw.UndoHistory = lambda *a, **k: UndoHistory(self.base / "u.sqlite")
        self.addCleanup(self._restore)

        cfg_path = self.base / "config.json"
        cfg_path.write_text(
            json.dumps({"threshold": 30.0, "theme": "dark",
                        "projects_dir": str(self.base / "proyectos")}),
            encoding="utf-8",
        )
        self.window = mw.MainWindow(ConfigManager(str(cfg_path)), QtLogHandler())
        self.addCleanup(self.window.close)
        self.avisos: list = []
        self.window._error = self.avisos.append
        self.window._info = self.avisos.append

    def _restore(self) -> None:
        mw.SessionStore, mw.UndoHistory = self._orig

    def _recomendacion(self):
        return recommend(discover_kmls(str(self.mes)))

    # ------------------------------------------------------------------
    def test_the_window_asks_for_the_adaptive_structure(self) -> None:
        self.assertTrue(self.window.renamer.adaptive_structure)

    def test_the_trace_is_filled_in_from_what_was_recognised(self) -> None:
        self.window._detect_is_auto = False
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(self.window.sidebar.kml_selector.value(), str(self.traza))

    def test_the_landmark_file_is_registered_too(self) -> None:
        self.window._detect_is_auto = False
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(self.window.config_manager.config.landmark_kmls, [str(self.vertederos)])

    def test_the_survey_file_is_never_chosen(self) -> None:
        self.window._on_kml_discovered(self._recomendacion())
        self.assertNotIn("Parcela.kml", self.window.sidebar.kml_selector.value())

    def test_a_manual_detection_explains_what_it_found(self) -> None:
        self.window._detect_is_auto = False
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(len(self.avisos), 1)
        self.assertIn("Puntos.kml", self.avisos[0])
        self.assertIn("Vertederos.kml", self.avisos[0])
        self.assertIn("Parcela.kml", self.avisos[0])      # y por que se ignoro

    def test_an_automatic_detection_does_not_pop_a_dialog(self) -> None:
        self.window._detect_is_auto = True
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(self.avisos, [])
        self.assertIn("Puntos.kml", self.window.status_message.text())

    def test_automatic_detection_keeps_landmark_files_the_operator_already_set(self) -> None:
        """Auto mode fills gaps; it does not rewrite a deliberate choice."""
        self.window.config_manager.update_config(landmark_kmls=["C:/mio/Otros.kml"])
        self.window._detect_is_auto = True
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(self.window.config_manager.config.landmark_kmls, ["C:/mio/Otros.kml"])

    def test_no_trace_found_is_said_not_guessed(self) -> None:
        self.traza.unlink()
        self.window._detect_is_auto = True
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(self.window.sidebar.kml_selector.value(), "")
        self.assertIn("No se ha reconocido ninguna traza", self.window.status_message.text())

    def test_choosing_a_folder_without_a_kml_starts_recognition(self) -> None:
        pedidos: list = []
        self.window._start_kml_discovery = lambda folder, auto: pedidos.append((folder, auto))

        self.window._on_folder_changed(str(self.mes))

        self.assertEqual(pedidos, [(str(self.mes), True)])

    def test_choosing_a_folder_never_overrides_a_kml_already_set(self) -> None:
        self.window.sidebar.set_values(kml_file=str(self.traza))
        pedidos: list = []
        self.window._start_kml_discovery = lambda folder, auto: pedidos.append((folder, auto))

        self.window._on_folder_changed(str(self.mes))

        self.assertEqual(pedidos, [])

    def _con_vertederos_en_la_traza(self) -> None:
        self.traza.write_text(trace_with_landfills("Caliche", "Gregal"), encoding="utf-8")

    def test_landfills_defined_in_the_kml_but_unknown_to_the_job_are_flagged(self) -> None:
        self._con_vertederos_en_la_traza()
        self.window.config_manager.update_config(extra_landmarks=[{"name": "Caliche", "lat": 37.8, "lon": -0.95}])
        self.window._detect_is_auto = False
        self.window._on_kml_discovered(self._recomendacion())

        self.assertIn("Gregal", self.avisos[0])
        self.assertIn("no tiene registrados", self.avisos[0])
        self.assertNotIn("  Caliche", self.avisos[0])      # ese si esta registrado

    def test_the_automatic_status_counts_them_without_a_dialog(self) -> None:
        self._con_vertederos_en_la_traza()
        self.window._detect_is_auto = True
        self.window._on_kml_discovered(self._recomendacion())

        self.assertEqual(self.avisos, [])
        self.assertIn("2 vertedero(s) del KML sin registrar", self.window.status_message.text())

    def test_registered_names_include_group_members(self) -> None:
        self.window.config_manager.update_config(
            landmark_groups=[{"name": "Caliche-Palomares", "folder": "Caliche-Palomares",
                              "members": ["Caliche", "Palomares"]}]
        )
        self.assertTrue({"Caliche", "Palomares"} <= self.window._registered_landmark_names())

    def _obra_activa(self):
        from src.core.projects import Project

        self.window._project_store.save(Project(name="Obra X", root=str(self.obra)))
        self.window.config_manager.update_config(active_project="Obra X")

    def test_recognised_landmark_files_are_kept_on_the_active_project(self) -> None:
        """Otherwise the next project switch overwrote them with an empty list."""
        self._obra_activa()
        self.window._detect_is_auto = False
        self.window._on_kml_discovered(self._recomendacion())

        guardada = self.window._project_store.find("Obra X")
        self.assertEqual(guardada.landmark_kmls, [str(self.vertederos)])

    def test_they_survive_switching_away_and_back(self) -> None:
        self._obra_activa()
        self.window._on_kml_discovered(self._recomendacion())
        self.window._apply_project(self.window._project_store.find("Obra X"), clear_analysis=True)

        self.assertEqual(self.window.config_manager.config.landmark_kmls, [str(self.vertederos)])

    def test_only_the_landmark_list_of_the_project_is_touched(self) -> None:
        from src.core.projects import Project

        self.window._project_store.save(
            Project(name="Obra X", root=str(self.obra), threshold=170.1, suffix="[PK]-AGO26",
                    viaduct_pks=["22+600"])
        )
        self.window.config_manager.update_config(active_project="Obra X")
        self.window._on_kml_discovered(self._recomendacion())

        guardada = self.window._project_store.find("Obra X")
        self.assertEqual((guardada.threshold, guardada.suffix, guardada.viaduct_pks),
                         (170.1, "[PK]-AGO26", ["22+600"]))

    def test_without_an_active_project_nothing_is_written(self) -> None:
        self.window._on_kml_discovered(self._recomendacion())
        self.assertEqual(self.window._project_store.load_all(), [])

    def test_the_button_without_a_folder_asks_for_one(self) -> None:
        self.window._on_detect_kml()
        self.assertEqual(len(self.avisos), 1)
        self.assertIn("carpeta", self.avisos[0])

    def test_the_trace_warning_points_at_the_detect_button(self) -> None:
        self.window._warn_about_the_trace({"kml_has_axis": False}, str(self.vertederos))
        self.assertIn("Detectar KML de la obra", self.avisos[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
