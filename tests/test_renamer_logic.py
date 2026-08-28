"""
Regression tests for RenamerLogic.
"""
import csv
import tempfile
import unittest
from pathlib import Path

from src.core.models import PhotoItem
from src.core.renamer_logic import (
    RenamerLogic,
    path_work_type_sort_prefix,
    photo_work_type_sort_key,
)


class _DummySpatialCalculator:
    project_axis = None

    def find_nearest_pk_name(self, lat, lon):
        return None, float("inf")

    def calculate_pk(self, lat, lon):
        return 0.0

    def is_landmark_name(self, name):
        return False

    def get_landmark_folder(self, name):
        return None


class TestRenamerLogic(unittest.TestCase):
    def test_work_type_vertedero_before_viaducto(self) -> None:
        v = PhotoItem(
            path="/proyecto/4.Abril/Vertederos/DJI_001.jpg",
            name="DJI_001.jpg",
            lat=0.0,
            lon=0.0,
            date_str="20260410",
            time_str="120000",
        )
        vi = PhotoItem(
            path="/proyecto/4.Abril/Viaductos_Norte/DJI_002.jpg",
            name="DJI_002.jpg",
            lat=0.0,
            lon=0.0,
            date_str="20260410",
            time_str="120000",
        )
        self.assertLess(photo_work_type_sort_key(v), photo_work_type_sort_key(vi))

    def test_work_type_viaducto_before_otros(self) -> None:
        vi = PhotoItem(
            path="/x/Viaductos/a.jpg",
            name="a.jpg",
            lat=0.0,
            lon=0.0,
            date_str="",
            time_str="",
        )
        o = PhotoItem(
            path="/x/Desmontes/b.jpg",
            name="b.jpg",
            lat=0.0,
            lon=0.0,
            date_str="",
            time_str="",
        )
        self.assertLess(photo_work_type_sort_key(vi), photo_work_type_sort_key(o))

    def test_work_type_puente_counts_as_viaducto_group(self) -> None:
        self.assertEqual(path_work_type_sort_prefix("/obra/Puentes PK12/f.jpg")[0], 1)

    def test_photo_work_type_sort_uses_exif_after_path(self) -> None:
        p = Path("/proyecto/Vertederos/a.jpg")
        early = PhotoItem(
            path=str(p),
            name="a.jpg",
            lat=0.0,
            lon=0.0,
            date_str="20260401",
            time_str="100000",
        )
        late = PhotoItem(
            path=str(p),
            name="a.jpg",
            lat=0.0,
            lon=0.0,
            date_str="20260401",
            time_str="120000",
        )
        self.assertLess(photo_work_type_sort_key(early), photo_work_type_sort_key(late))

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.logic = RenamerLogic(_DummySpatialCalculator())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_preview_names_respects_threshold_changes(self) -> None:
        item = PhotoItem(
            path=str(Path(self.temp_dir) / "foto_02.JPG"),
            name="foto_02.JPG",
            lat=40.0,
            lon=-3.0,
            date_str="20260421",
            time_str="101530",
            nearest_name="PK 1",
            distance=50.0,
        )
        self.logic.build_preview_names([item], threshold=100.0, template="[PK]")
        self.assertTrue(item.is_inside_threshold)

        self.logic.build_preview_names([item], threshold=10.0, template="[PK]")
        self.assertFalse(item.is_inside_threshold)

    def test_renamer_honours_max_workers_setting(self) -> None:
        logic = RenamerLogic(_DummySpatialCalculator(), max_workers=8)
        self.assertEqual(logic.max_workers, 8)

    def test_build_preview_names_uses_template_placeholders(self):
        item = PhotoItem(
            path=str(Path(self.temp_dir) / "foto_01.JPG"),
            name="foto_01.JPG",
            lat=40.0,
            lon=-3.0,
            date_str="20260421",
            time_str="101530",
            nearest_name="PK 12+034",
            distance=15.0,
        )

        preview = self.logic.build_preview_names([item], threshold=30.0, template="[PK]-[ORIG]-[FECHA]-[HORA]")
        self.assertEqual(len(preview), 1)
        self.assertTrue(item.is_inside_threshold)
        self.assertEqual(item.new_name_base, "PK-12+034-foto_01-20260421-101530")

    def test_undo_last_rename_handles_duplicate_new_names_in_different_dirs(self):
        base = Path(self.temp_dir)
        dir_a = base / "a"
        dir_b = base / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        renamed_name = "PK-1-001.jpg"
        original_a = "orig_a.jpg"
        original_b = "orig_b.jpg"

        (dir_a / renamed_name).write_bytes(b"a")
        (dir_b / renamed_name).write_bytes(b"b")

        csv_path = base / "reporte_renombrado.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["original", "nuevo", "pk", "distancia"])
            writer.writeheader()
            writer.writerow({"original": original_a, "nuevo": renamed_name, "pk": "PK-1", "distancia": "1.0"})
            writer.writerow({"original": original_b, "nuevo": renamed_name, "pk": "PK-1", "distancia": "1.2"})

        ok, message = self.logic.undo_last_rename_from_csv(str(base))
        self.assertTrue(ok, msg=message)
        self.assertTrue((dir_a / original_a).exists())
        self.assertTrue((dir_b / original_b).exists())
        self.assertFalse((dir_a / renamed_name).exists())
        self.assertFalse((dir_b / renamed_name).exists())


    def test_undo_csv_reports_failure_when_nothing_reverted(self) -> None:
        base = Path(self.temp_dir)
        csv_path = base / "reporte_renombrado.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["original", "nuevo", "pk", "distancia"])
            writer.writeheader()
            writer.writerow(
                {"original": "missing.jpg", "nuevo": "gone.jpg", "pk": "PK-1", "distancia": "1.0"}
            )
        ok, message = self.logic.undo_last_rename_from_csv(str(base))
        self.assertFalse(ok)
        self.assertIn("No se pudo revertir", message)


if __name__ == "__main__":
    unittest.main()
