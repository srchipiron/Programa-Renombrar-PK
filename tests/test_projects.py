"""Per-corridor project definitions.

Switching corridor used to mean editing seven fields of a global config by
hand, and forgetting failed silently: Torre Pacheco's landfills are 200 km from
the Lorca-Pulpí trace so they never capture a photo, and its viaduct PKs
(22+600) never match a 400+ km chainage — yet ``ensure_work_folders`` still
created ``VERTEDEROS/Caliche-Palomares`` inside the other client's delivery.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.core.config import AppConfig
from src.core.projects import (
    Project,
    ProjectStore,
    bootstrap_from_config,
    guess_project_root,
    project_from_config,
    slugify,
)

CLIENTES = "//dsconecta/aeroscan/01. PRODUCCION AEROSCAN/TRABAJOS/CLIENTES"
TORRE = f"{CLIENTES}/UTE ACCIONA-AZVI TRAMO TORRE PACHECO"
LORCA = f"{CLIENTES}/UTE AVE TRAZA LORCA-PULPI"


class SlugifyTests(unittest.TestCase):
    def test_accents_and_spaces_become_a_safe_stem(self) -> None:
        self.assertEqual(slugify("UTE AVE TRAZA LORCA-PULPÍ"), "ute-ave-traza-lorca-pulpi")
        self.assertEqual(slugify("Torre Pacheco"), "torre-pacheco")

    def test_never_returns_an_empty_name(self) -> None:
        self.assertEqual(slugify(""), "proyecto")
        self.assertEqual(slugify("///"), "proyecto")


class ProjectTests(unittest.TestCase):
    def test_contains_matches_the_delivery_tree(self) -> None:
        project = Project(name="Torre Pacheco", root=TORRE)
        self.assertTrue(project.contains(f"{TORRE}/2026/8.Agosto"))
        self.assertTrue(project.contains(TORRE))
        self.assertFalse(project.contains(f"{LORCA}/2026/7.JULIO"))

    def test_a_sibling_with_a_longer_name_is_not_inside(self) -> None:
        """Prefix matching would put ``…PULPI-VERA-2`` inside ``…PULPI-VERA``."""
        project = Project(name="Pulpi-Vera", root=f"{CLIENTES}/TRAZA PULPI-VERA")
        self.assertFalse(project.contains(f"{CLIENTES}/TRAZA PULPI-VERA-2/2026"))

    def test_empty_root_matches_nothing(self) -> None:
        self.assertFalse(Project(name="sin raiz").contains(f"{TORRE}/2026"))

    def test_from_dict_ignores_unknown_and_broken_fields(self) -> None:
        project = Project.from_dict(
            {
                "name": "  Torre Pacheco  ",
                "kml": "x.kml",
                "threshold": "170.1",
                "landmark_capture_radius": "no es un numero",
                "viaduct_pks": ["22+600", "  ", 23100],
                "extra_landmarks": [{"name": "Gregal"}, "basura"],
                "campo_de_una_version_futura": 1,
            }
        )
        self.assertEqual(project.name, "Torre Pacheco")
        self.assertEqual(project.threshold, 170.1)
        self.assertEqual(project.landmark_capture_radius, 450.0)  # default kept
        self.assertEqual(project.viaduct_pks, ["22+600", "23100"])
        self.assertEqual(project.extra_landmarks, [{"name": "Gregal"}])

    def test_round_trips_through_json(self) -> None:
        original = Project(name="Lorca-Pulpí", root=LORCA, kml="t.kml", threshold=20.0)
        restored = Project.from_dict(json.loads(json.dumps(original.to_dict())))
        self.assertEqual(restored, original)


class ProjectStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / "proyectos")

    def test_save_and_load(self) -> None:
        self.store.save(Project(name="Torre Pacheco", root=TORRE, threshold=170.1))
        self.store.save(Project(name="Lorca-Pulpí", root=LORCA, threshold=20.0))

        nombres = [p.name for p in self.store.load_all()]
        self.assertEqual(nombres, ["Lorca-Pulpí", "Torre Pacheco"])  # ordenado
        self.assertEqual(self.store.find("torre pacheco").threshold, 170.1)
        self.assertIsNone(self.store.find("no existe"))

    def test_missing_directory_is_empty_not_an_error(self) -> None:
        self.assertEqual(self.store.load_all(), [])
        self.assertIsNone(self.store.match_for_path(f"{TORRE}/2026"))

    def test_a_broken_file_does_not_hide_the_others(self) -> None:
        self.store.save(Project(name="Bueno", root=TORRE))
        (self.store.directory / "roto.json").write_text("{no es json", encoding="utf-8")
        (self.store.directory / "lista.json").write_text("[1, 2]", encoding="utf-8")

        self.assertEqual([p.name for p in self.store.load_all()], ["Bueno"])

    def test_match_for_path_picks_the_right_corridor(self) -> None:
        self.store.save(Project(name="Torre Pacheco", root=TORRE))
        self.store.save(Project(name="Lorca-Pulpí", root=LORCA))

        match = self.store.match_for_path(f"{LORCA}/2026/7.JULIO/Imagenes")
        self.assertIsNotNone(match)
        self.assertEqual(match.name, "Lorca-Pulpí")
        self.assertIsNone(self.store.match_for_path("G:/otra/cosa"))

    def test_the_deepest_root_wins(self) -> None:
        self.store.save(Project(name="Todo", root=CLIENTES))
        self.store.save(Project(name="Torre Pacheco", root=TORRE))
        match = self.store.match_for_path(f"{TORRE}/2026/8.Agosto")
        self.assertEqual(match.name, "Torre Pacheco")

    def test_saving_the_same_name_overwrites_instead_of_duplicating(self) -> None:
        self.store.save(Project(name="Torre Pacheco", threshold=30.0))
        self.store.save(Project(name="Torre Pacheco", threshold=170.1))
        proyectos = self.store.load_all()
        self.assertEqual(len(proyectos), 1)
        self.assertEqual(proyectos[0].threshold, 170.1)

    def test_delete(self) -> None:
        self.store.save(Project(name="Temporal"))
        self.assertTrue(self.store.delete("temporal"))
        self.assertEqual(self.store.load_all(), [])
        self.assertFalse(self.store.delete("temporal"))


class RootGuessTests(unittest.TestCase):
    def test_uses_the_client_folder_of_the_production_tree(self) -> None:
        root, name = guess_project_root(f"{TORRE}/2026/8.Agosto")
        self.assertEqual(name, "UTE ACCIONA-AZVI TRAMO TORRE PACHECO")
        self.assertTrue(root.replace("\\", "/").endswith("UTE ACCIONA-AZVI TRAMO TORRE PACHECO"))

    def test_falls_back_to_the_parent_folder(self) -> None:
        root, name = guess_project_root("", "G:/obra/traza.kml")
        self.assertEqual(name, "obra")
        self.assertTrue(root.replace("\\", "/").endswith("G:/obra"))

    def test_nothing_to_guess(self) -> None:
        self.assertIsNone(guess_project_root("", ""))


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ProjectStore(Path(self.tmp.name) / "proyectos")

    def _config(self) -> AppConfig:
        return AppConfig(
            last_folder=f"{TORRE}/2026/8.Agosto",
            last_kml=f"{TORRE}/Puntos para script.kml",
            last_suffix="[PK]-AGO26",
            threshold=170.1,
            extra_landmarks=[{"name": "Gregal", "lat": 37.7, "lon": -0.95}],
            landmark_groups=[
                {"members": ["Caliche", "Palomares"], "name": "Caliche-Palomares",
                 "folder": "Caliche-Palomares"}
            ],
            viaduct_pks=["22+600", "22+800"],
        )

    def test_seeds_the_first_project_from_the_existing_settings(self) -> None:
        project = bootstrap_from_config(self.store, self._config())

        self.assertIsNotNone(project)
        self.assertEqual(project.name, "UTE ACCIONA-AZVI TRAMO TORRE PACHECO")
        self.assertEqual(project.threshold, 170.1)
        self.assertEqual(project.suffix, "[PK]-AGO26")
        self.assertEqual(project.viaduct_pks, ["22+600", "22+800"])
        self.assertEqual(len(project.landmark_groups), 1)
        self.assertTrue(project.contains(f"{TORRE}/2026/9.Septiembre"))
        self.assertEqual([p.name for p in self.store.load_all()], [project.name])

    def test_does_not_run_twice(self) -> None:
        self.store.save(Project(name="Ya existe"))
        self.assertIsNone(bootstrap_from_config(self.store, self._config()))

    def test_nothing_to_migrate_without_a_trace(self) -> None:
        self.assertIsNone(bootstrap_from_config(self.store, AppConfig()))
        self.assertEqual(self.store.load_all(), [])

    def test_project_from_config_keeps_the_landmark_files(self) -> None:
        cfg = self._config()
        cfg.landmark_kmls = [f"{TORRE}/Vertederos.kml"]
        self.assertEqual(project_from_config(cfg).landmark_kmls, cfg.landmark_kmls)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
