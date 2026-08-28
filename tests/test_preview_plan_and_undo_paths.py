"""Preview plan fidelity + relative-path undo (folder restore)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.core.models import PhotoItem
from src.core.rename_report import (
    load_rename_mapping,
    relative_mapping_key,
    undo_rename_operations,
)
from src.core.renamer_logic import RenamerLogic
from src.ui_qt.undo_history import UndoHistory, apply_undo


class _Spatial:
    project_axis = None
    viaduct = False

    def find_nearest_pk_name(self, lat, lon):
        return "PK-1+000", 5.0

    def calculate_pk(self, lat, lon):
        return 1000.0

    def get_landmark_folder(self, name):
        return None

    def is_landmark_name(self, name):
        return False


class _ViaductSpatial(_Spatial):
    def __init__(self) -> None:
        self.viaduct = True


class TestPreviewPlan(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.logic = RenamerLogic(_Spatial())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _item(self, name: str, base: str, *, view: str = "") -> PhotoItem:
        path = os.path.join(self.folder, name)
        Image.new("RGB", (4, 4), color=(1, 2, 3)).save(path, format="JPEG")
        return PhotoItem(
            path=path,
            name=name,
            lat=40.0,
            lon=-3.0,
            distance=5.0,
            pk_value=1000.0,
            nearest_name="PK-1+000",
            is_inside_threshold=True,
            new_name_base=base,
            view_label=view,
            date_str="20260801",
            time_str="120000",
        )

    def test_preview_plan_adds_sequence_and_extension(self) -> None:
        a = self._item("a.jpg", "PK-1+000-[PK]")
        a.time_str = "120000"
        b = self._item("b.jpg", "PK-1+000-[PK]")
        b.time_str = "120001"
        plan = self.logic.build_preview_plan([a, b], self.folder)
        self.assertEqual(plan[a.path], "PK-1+000-[PK]_01.jpg")
        self.assertEqual(plan[b.path], "PK-1+000-[PK]_02.jpg")

    def test_assign_destination_marks_viaductos(self) -> None:
        self.logic.set_viaduct_pks(["1+000"])
        item = self._item("a.jpg", "PK-1+000-[PK]", view="TI")
        self.logic.assign_destination_folders([item], self.folder)
        self.assertEqual(item.dest_rel, "VIADUCTOS")


class TestRelativePathUndo(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.logic = RenamerLogic(_Spatial())
        self.logic.set_viaduct_pks(["1+000"])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_process_images_records_relative_mapping_and_undo_restores_root(self) -> None:
        src = self.folder / "DJI_100.jpg"
        Image.new("RGB", (4, 4), color=(9, 9, 9)).save(src, format="JPEG")
        item = PhotoItem(
            path=str(src),
            name="DJI_100.jpg",
            lat=40.0,
            lon=-3.0,
            distance=5.0,
            pk_value=1000.0,
            nearest_name="PK-1+000",
            is_inside_threshold=True,
            new_name_base="PK-1+000-[PK]",
            view_label="TI",
        )
        stats = self.logic.process_images(
            [item],
            str(self.folder),
            create_backup=False,
            progress_cb=lambda *_a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 1)
        mapping = stats["mapping"]
        # nuevo is relative under VIADUCTOS/
        self.assertTrue(any(k.startswith("VIADUCTOS/") for k in mapping))
        new_rel = next(iter(mapping))
        self.assertEqual(mapping[new_rel], "DJI_100.jpg")
        self.assertTrue((self.folder / "VIADUCTOS" / Path(new_rel).name).is_file())
        self.assertFalse(src.exists())

        # CSV channel
        csv_map = load_rename_mapping(self.folder)
        self.assertEqual(csv_map[new_rel], "DJI_100.jpg")

        ok, msg = self.logic.undo_last_rename_from_csv(str(self.folder))
        self.assertTrue(ok, msg)
        self.assertTrue(src.is_file())
        self.assertFalse((self.folder / "VIADUCTOS" / Path(new_rel).name).exists())

    def test_sqlite_apply_undo_moves_back_from_subdir(self) -> None:
        viad = self.folder / "VIADUCTOS"
        viad.mkdir()
        renamed = viad / "PK-1.jpg"
        renamed.write_bytes(b"x")
        history = UndoHistory(self.folder / "undo.sqlite")
        history.record(
            str(self.folder),
            {"VIADUCTOS/PK-1.jpg": "original.jpg"},
        )
        entry = history.latest_for_folder(str(self.folder))
        self.assertIsNotNone(entry)
        summary = apply_undo(entry)
        self.assertEqual(summary["ok"], 1)
        self.assertTrue((self.folder / "original.jpg").is_file())
        self.assertFalse(renamed.exists())

    def test_legacy_basename_undo_still_works(self) -> None:
        renamed = self.folder / "PK-legacy.jpg"
        renamed.write_bytes(b"y")
        summary = undo_rename_operations(
            self.folder,
            [("PK-legacy.jpg", "old.jpg")],
        )
        self.assertEqual(summary["ok"], 1)
        self.assertTrue((self.folder / "old.jpg").is_file())

    def test_relative_mapping_key_normalizes_slashes(self) -> None:
        nested = self.folder / "VIADUCTOS" / "a.jpg"
        nested.parent.mkdir(parents=True, exist_ok=True)
        nested.write_bytes(b"z")
        key = relative_mapping_key(nested, self.folder)
        self.assertEqual(key, "VIADUCTOS/a.jpg")


if __name__ == "__main__":
    unittest.main()
