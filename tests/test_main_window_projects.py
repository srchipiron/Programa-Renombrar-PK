"""The corridor selector, driven through a real MainWindow.

Each corridor carries its own trace, landfills, viaduct PKs, threshold and
suffix. Applying the wrong ones fails silently — landfills 200 km away never
capture a photo — so these tests cover the switch, the automatic detection from
the chosen folder and the guard that catches the mismatch.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets")

from src.core.config import ConfigManager  # noqa: E402
from src.core.models import PhotoItem  # noqa: E402
from src.core.projects import Project, ProjectStore  # noqa: E402
from src.ui_qt import main_window as mw  # noqa: E402
from src.ui_qt.log_handler import QtLogHandler  # noqa: E402
from src.ui_qt.session_store import SessionStore  # noqa: E402
from src.ui_qt.undo_history import UndoHistory  # noqa: E402

_HEADER = '<?xml version="1.0" encoding="UTF-8"?>'


def _kml_text(pk_name: str, lon: float) -> str:
    return (
        f'{_HEADER}\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<Placemark><LineString><coordinates>"
        f"{lon},37.8000,0 {lon + 0.01},37.8100,0"
        f"</coordinates></LineString></Placemark>"
        f"<Placemark><name>{pk_name}</name><Point>"
        f"<coordinates>{lon},37.8000,0</coordinates></Point></Placemark>"
        f"</Document></kml>"
    )


class ProjectSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

        # Dos obras con su arbol de entrega, como en produccion.
        self.torre_root = self.base / "CLIENTES" / "TORRE PACHECO"
        self.lorca_root = self.base / "CLIENTES" / "LORCA-PULPI"
        for root, pk, lon in ((self.torre_root, "PK-18+000", -0.96), (self.lorca_root, "PK-400+500", -1.60)):
            (root / "2026" / "8.Agosto").mkdir(parents=True)
            (root / "traza.kml").write_text(_kml_text(pk, lon), encoding="utf-8")

        self.projects_dir = self.base / "proyectos"
        store = ProjectStore(self.projects_dir)
        store.save(
            Project(
                name="Torre Pacheco",
                root=str(self.torre_root),
                kml=str(self.torre_root / "traza.kml"),
                threshold=170.1,
                suffix="[PK]-AGO26",
                viaduct_pks=["22+600"],
                extra_landmarks=[{"name": "Gregal", "lat": 37.80, "lon": -0.955}],
            )
        )
        store.save(
            Project(
                name="Lorca-Pulpí",
                root=str(self.lorca_root),
                kml=str(self.lorca_root / "traza.kml"),
                threshold=20.0,
                suffix="[PK]-JUL26",
            )
        )

        self._orig = (mw.SessionStore, mw.UndoHistory)
        mw.SessionStore = lambda *a, **k: SessionStore(self.base / "s.json")
        mw.UndoHistory = lambda *a, **k: UndoHistory(self.base / "u.sqlite")
        self.addCleanup(self._restore)

        cfg_path = self.base / "config.json"
        cfg_path.write_text(
            json.dumps({"threshold": 30.0, "theme": "dark",
                        "projects_dir": str(self.projects_dir)}),
            encoding="utf-8",
        )
        self.window = mw.MainWindow(ConfigManager(str(cfg_path)), QtLogHandler())
        self.addCleanup(self.window.close)
        # Los dialogos modales bloquearian la suite: se registran en su lugar.
        self.avisos: list = []
        self.window._error = self.avisos.append
        self.window._info = self.avisos.append

    def _restore(self) -> None:
        mw.SessionStore, mw.UndoHistory = self._orig

    # ------------------------------------------------------------------
    def test_selector_lists_the_corridors(self) -> None:
        combo = self.window.sidebar.project_combo
        etiquetas = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(etiquetas, ["(sin obra)", "Lorca-Pulpí", "Torre Pacheco"])

    def test_choosing_a_corridor_loads_its_rules(self) -> None:
        self.window._on_project_changed("Torre Pacheco")

        cfg = self.window.config_manager.config
        self.assertEqual(cfg.active_project, "Torre Pacheco")
        self.assertEqual(cfg.threshold, 170.1)
        self.assertEqual(cfg.viaduct_pks, ["22+600"])
        self.assertEqual(self.window.sidebar.get_config().suffix, "[PK]-AGO26")
        self.assertEqual(self.window.sidebar.get_config().threshold, 170.1)
        # La traza queda cargada y los viaductos llegan al renamer.
        self.assertEqual(self.window._loaded_kml_path, str(self.torre_root / "traza.kml"))
        self.assertIn("22+600", self.window.renamer.viaduct_pks)
        self.assertTrue(self.window.spatial_calc.is_landmark_name("Gregal"))

    def test_switching_corridor_drops_the_previous_analysis(self) -> None:
        """Photos measured against another trace mean nothing here."""
        self.window._on_project_changed("Torre Pacheco")
        self.window._analysis_items = [
            PhotoItem(path="a.jpg", name="a.jpg", lat=37.8, lon=-0.96,
                      pk_value=18000.0, is_inside_threshold=True)
        ]

        self.window._on_project_changed("Lorca-Pulpí")

        self.assertEqual(self.window._analysis_items, [])
        self.assertEqual(self.window.config_manager.config.threshold, 20.0)
        # Los vertederos de la obra anterior no sobreviven al cambio.
        self.assertEqual(self.window.config_manager.config.extra_landmarks, [])

    def test_the_folder_selects_the_corridor(self) -> None:
        self.window._on_project_changed("Torre Pacheco")

        self.window._on_folder_changed(str(self.lorca_root / "2026" / "8.Agosto"))

        self.assertEqual(self.window.config_manager.config.active_project, "Lorca-Pulpí")
        self.assertEqual(self.window.sidebar.current_project(), "Lorca-Pulpí")
        self.assertIn("Lorca-Pulpí", self.window.status_message.text())

    def test_a_folder_of_the_active_corridor_changes_nothing(self) -> None:
        self.window._on_project_changed("Torre Pacheco")
        self.window._on_folder_changed(str(self.torre_root / "2026" / "8.Agosto"))
        self.assertEqual(self.window.config_manager.config.active_project, "Torre Pacheco")

    def test_an_unknown_folder_leaves_the_corridor_alone(self) -> None:
        self.window._on_project_changed("Torre Pacheco")
        ajena = self.base / "fuera"
        ajena.mkdir()
        self.window._on_folder_changed(str(ajena))
        self.assertEqual(self.window.config_manager.config.active_project, "Torre Pacheco")

    def test_guard_reports_a_folder_outside_the_active_corridor(self) -> None:
        self.window._on_project_changed("Torre Pacheco")

        fuera = self.window._folder_outside_active_project(
            str(self.lorca_root / "2026" / "8.Agosto")
        )
        dentro = self.window._folder_outside_active_project(
            str(self.torre_root / "2026" / "8.Agosto")
        )

        self.assertIsNotNone(fuera)
        self.assertEqual(fuera.name, "Torre Pacheco")
        self.assertIsNone(dentro)

    def test_no_active_corridor_means_no_guard(self) -> None:
        self.assertIsNone(
            self.window._folder_outside_active_project(str(self.lorca_root))
        )

    def test_a_deleted_corridor_is_reported_and_the_list_refreshed(self) -> None:
        os.remove(self.projects_dir / "torre-pacheco.json")
        self.window._on_project_changed("Torre Pacheco")
        combo = self.window.sidebar.project_combo
        etiquetas = [combo.itemText(i) for i in range(combo.count())]
        self.assertNotIn("Torre Pacheco", etiquetas)
        self.assertTrue(any("Torre Pacheco" in str(a) for a in self.avisos))


class BootstrapOnStartTests(unittest.TestCase):
    """Upgrading from the single global config must not lose the setup."""

    def test_first_run_seeds_a_corridor_from_the_existing_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "CLIENTES" / "OBRA X"
            (root / "2026").mkdir(parents=True)
            kml = root / "traza.kml"
            kml.write_text(_kml_text("PK-1+000", -0.96), encoding="utf-8")

            orig = (mw.SessionStore, mw.UndoHistory)
            mw.SessionStore = lambda *a, **k: SessionStore(base / "s.json")
            mw.UndoHistory = lambda *a, **k: UndoHistory(base / "u.sqlite")
            try:
                cfg_path = base / "config.json"
                cfg_path.write_text(
                    json.dumps(
                        {
                            "last_folder": str(root / "2026"),
                            "last_kml": str(kml),
                            "last_suffix": "[PK]-AGO26",
                            "threshold": 170.1,
                            "viaduct_pks": ["22+600"],
                            "projects_dir": str(base / "proyectos"),
                        }
                    ),
                    encoding="utf-8",
                )
                window = mw.MainWindow(ConfigManager(str(cfg_path)), QtLogHandler())
                window._error = lambda *_a, **_k: None
                window._info = lambda *_a, **_k: None
                try:
                    proyectos = ProjectStore(base / "proyectos").load_all()
                    self.assertEqual([p.name for p in proyectos], ["OBRA X"])
                    self.assertEqual(proyectos[0].threshold, 170.1)
                    self.assertEqual(proyectos[0].viaduct_pks, ["22+600"])
                    combo = window.sidebar.project_combo
                    self.assertIn(
                        "OBRA X", [combo.itemText(i) for i in range(combo.count())]
                    )
                    # Queda activa: es lo que arma el aviso de carpeta ajena
                    # ya en el primer arranque, sin tener que elegirla a mano.
                    self.assertEqual(
                        window.config_manager.config.active_project, "OBRA X"
                    )
                    self.assertEqual(window.sidebar.current_project(), "OBRA X")
                    self.assertIsNotNone(
                        window._folder_outside_active_project(str(base / "otra obra"))
                    )
                finally:
                    window.close()
            finally:
                mw.SessionStore, mw.UndoHistory = orig


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
