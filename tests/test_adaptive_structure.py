"""The work folders follow the job, not Torre Pacheco's convention.

The program created OTROS / VIADUCTOS / VERTEDEROS for every job. That is what
real Torre Pacheco deliveries contain (six of eight months on the share), but
Pulpí-Vera is delivered as Enlace / Traza and its KML defines no landfills and
no viaducts: the classic tree there is three empty folders in a client's
delivery that were never asked for.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from src.core.renamer_logic import RenamerLogic


class _Calc:
    """Minimal calculator: landmarks come from ``landmark_names``."""

    project_axis = None
    named_points: list = []
    _landmark_groups: list = []
    _landmark_names: set = set()

    def is_landmark_name(self, name):
        return False


class WorkRootsTests(unittest.TestCase):
    def logic(self, *, adaptive: bool, viaducts=()) -> RenamerLogic:
        logic = RenamerLogic(_Calc())
        logic.adaptive_structure = adaptive
        logic.set_viaduct_pks(list(viaducts))
        return logic

    def test_the_default_is_still_the_classic_tree(self) -> None:
        """Direct callers and every existing test keep what they always got."""
        self.assertEqual(
            self.logic(adaptive=False).work_roots(has_landmarks=False),
            ("OTROS", "VIADUCTOS", "VERTEDEROS"),
        )

    def test_a_job_with_nothing_to_route_gets_no_folders(self) -> None:
        """Pulpí-Vera: 261 PK posts, no landfills, no viaducts."""
        self.assertEqual(self.logic(adaptive=True).work_roots(has_landmarks=False), ())

    def test_landmarks_give_vertederos(self) -> None:
        roots = self.logic(adaptive=True).work_roots(has_landmarks=True)
        self.assertEqual(roots, ("OTROS", "VERTEDEROS"))

    def test_viaduct_pks_give_viaductos(self) -> None:
        roots = self.logic(adaptive=True, viaducts=["22+600"]).work_roots(has_landmarks=False)
        self.assertEqual(roots, ("OTROS", "VIADUCTOS"))

    def test_both_give_the_full_classic_tree_in_its_usual_order(self) -> None:
        roots = self.logic(adaptive=True, viaducts=["22+600"]).work_roots(has_landmarks=True)
        self.assertEqual(roots, ("OTROS", "VIADUCTOS", "VERTEDEROS"))

    def test_otros_never_appears_alone(self) -> None:
        """It only accompanies a folder that is actually used."""
        self.assertNotIn("OTROS", self.logic(adaptive=True).work_roots(has_landmarks=False))


class EnsureWorkFoldersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name

    def listing(self):
        return sorted(os.listdir(self.folder))

    def test_adaptive_creates_nothing_for_a_job_without_landmarks_or_viaducts(self) -> None:
        logic = RenamerLogic(_Calc())
        logic.adaptive_structure = True
        creadas = logic.ensure_work_folders(self.folder)
        self.assertEqual(creadas, [])
        self.assertEqual(self.listing(), [])

    def test_adaptive_creates_the_landmark_subfolders_it_was_given(self) -> None:
        logic = RenamerLogic(_Calc())
        logic.adaptive_structure = True
        logic.ensure_work_folders(self.folder, landmark_names=["Gregal", "Caliche"])
        self.assertEqual(self.listing(), ["OTROS", "VERTEDEROS"])
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.folder, "VERTEDEROS"))), ["Caliche", "Gregal"]
        )

    def test_adaptive_with_viaducts_only_skips_vertederos(self) -> None:
        logic = RenamerLogic(_Calc())
        logic.adaptive_structure = True
        logic.set_viaduct_pks(["22+600"])
        logic.ensure_work_folders(self.folder)
        self.assertEqual(self.listing(), ["OTROS", "VIADUCTOS"])

    def test_the_default_still_creates_the_classic_tree(self) -> None:
        RenamerLogic(_Calc()).ensure_work_folders(self.folder)
        self.assertEqual(self.listing(), sorted(["OTROS", "VIADUCTOS", "VERTEDEROS"]))

    def test_a_photo_for_a_missing_folder_still_gets_it_on_demand(self) -> None:
        """Skipping the scaffold must not stop viaduct photos reaching VIADUCTOS.

        process_images creates each photo's destination as it goes, so the
        scaffold was only ever cosmetic.
        """
        from PIL import Image

        from src.core.models import PhotoItem

        calc = _Calc()
        calc.find_nearest_pk_name = lambda lat, lon: ("PK-1+000", 5.0)
        calc.calculate_pk = lambda lat, lon: 1000.0
        calc.get_landmark_folder = lambda name: None
        logic = RenamerLogic(calc)
        logic.adaptive_structure = True
        logic.set_viaduct_pks(["1+000"])

        ruta = os.path.join(self.folder, "DJI_001.JPG")
        Image.new("RGB", (8, 8)).save(ruta, "JPEG")
        item = PhotoItem(
            path=ruta, name="DJI_001.JPG", lat=40.0, lon=-3.0, date_str="20260601",
            time_str="120000", nearest_name="PK-1+000", distance=5.0, pk_value=1000.0,
            is_inside_threshold=True, new_name_base="PK-1+000",
        )
        stats = logic.process_images(
            [item], self.folder, create_backup=False,
            progress_cb=lambda d, t, m: None, check_cancel=lambda: False,
        )

        self.assertEqual(stats["ok"], 1)
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "VIADUCTOS", "PK-1+000.jpg")))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
