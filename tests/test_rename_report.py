"""Tests for rename report CSV helpers."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.core.rename_report import (
    RENAME_REPORT_FILENAME,
    load_rename_mapping,
    load_rename_operations,
    relative_mapping_key,
    report_csv_path,
    undo_rename_operations,
)


class TestRenameReport(unittest.TestCase):
    def test_report_path_and_load_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            csv_path = folder / RENAME_REPORT_FILENAME
            with open(csv_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["original", "nuevo", "pk", "distancia"])
                writer.writeheader()
                writer.writerow(
                    {"original": "a.jpg", "nuevo": "PK-1.jpg", "pk": "PK1", "distancia": "1.0"}
                )

            self.assertEqual(report_csv_path(folder), csv_path)
            mapping = load_rename_mapping(folder)
            self.assertEqual(mapping, {"PK-1.jpg": "a.jpg"})

    def test_missing_report_returns_empty_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_rename_mapping(tmp), {})

    def test_operations_preserves_duplicate_new_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            csv_path = folder / RENAME_REPORT_FILENAME
            with open(csv_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["original", "nuevo", "pk", "distancia"])
                writer.writeheader()
                writer.writerow({"original": "a.jpg", "nuevo": "same.jpg", "pk": "1", "distancia": "1"})
                writer.writerow({"original": "b.jpg", "nuevo": "same.jpg", "pk": "1", "distancia": "2"})
            ops = load_rename_operations(folder)
            self.assertEqual(ops, [("same.jpg", "a.jpg"), ("same.jpg", "b.jpg")])
            self.assertEqual(load_rename_mapping(folder), {"same.jpg": "b.jpg"})


class TestUndoOrdering(unittest.TestCase):
    """A batch that frees a name and reuses it must undo completely.

    ``process_images`` renames sequentially, so job N can legitimately take a
    name that job N-1 just vacated (``A→B`` then ``C→A``). Replaying those
    forwards tries to restore ``B→A`` while ``A`` is still occupied and gives
    up with a conflict, leaving a file renamed even though the batch is fully
    reversible.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_reused_name_is_fully_reverted(self) -> None:
        (self.base / "B.jpg").write_bytes(b"soy-A")
        (self.base / "A.jpg").write_bytes(b"soy-C")
        operations = [("B.jpg", "A.jpg"), ("A.jpg", "C.jpg")]  # orden de renombrado

        summary = undo_rename_operations(self.base, operations)

        self.assertEqual(summary, {"ok": 2, "missing": 0, "conflict": 0})
        self.assertEqual((self.base / "A.jpg").read_bytes(), b"soy-A")
        self.assertEqual((self.base / "C.jpg").read_bytes(), b"soy-C")
        self.assertFalse((self.base / "B.jpg").exists())

    def test_reused_name_across_subfolders(self) -> None:
        (self.base / "VIADUCTOS").mkdir()
        (self.base / "VIADUCTOS" / "PK-2+000.jpg").write_bytes(b"primera")
        (self.base / "PK-1+000.jpg").write_bytes(b"segunda")
        operations = [
            ("VIADUCTOS/PK-2+000.jpg", "PK-1+000.jpg"),
            ("PK-1+000.jpg", "DJI_0002.jpg"),
        ]

        summary = undo_rename_operations(self.base, operations)

        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["conflict"], 0)
        self.assertEqual((self.base / "PK-1+000.jpg").read_bytes(), b"primera")
        self.assertEqual((self.base / "DJI_0002.jpg").read_bytes(), b"segunda")

    def test_three_step_chain(self) -> None:
        # A→B, C→A, D→C recorded in that order.
        (self.base / "B.jpg").write_bytes(b"soy-A")
        (self.base / "A.jpg").write_bytes(b"soy-C")
        (self.base / "C.jpg").write_bytes(b"soy-D")
        operations = [("B.jpg", "A.jpg"), ("A.jpg", "C.jpg"), ("C.jpg", "D.jpg")]

        summary = undo_rename_operations(self.base, operations)

        self.assertEqual(summary["ok"], 3)
        self.assertEqual((self.base / "A.jpg").read_bytes(), b"soy-A")
        self.assertEqual((self.base / "C.jpg").read_bytes(), b"soy-C")
        self.assertEqual((self.base / "D.jpg").read_bytes(), b"soy-D")


class TestRelativeUndo(unittest.TestCase):
    def test_nested_nuevo_restores_basename_original_to_base_root(self) -> None:
        """Cross-dir rename: original at root must not land next to nested nuevo."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "VIADUCTOS").mkdir()
            (base / "Z_other").mkdir()
            (base / "VIADUCTOS" / "PK-1+000.jpg").write_bytes(b"PHOTO")
            (base / "Z_other" / "PK-1+000.jpg").write_bytes(b"DECOY")

            summary = undo_rename_operations(
                base, [("VIADUCTOS/PK-1+000.jpg", "src.jpg")]
            )
            self.assertEqual(summary["ok"], 1)
            self.assertEqual(summary["missing"], 0)
            self.assertTrue((base / "src.jpg").is_file())
            self.assertEqual((base / "src.jpg").read_bytes(), b"PHOTO")
            self.assertFalse((base / "VIADUCTOS" / "src.jpg").exists())
            self.assertFalse((base / "VIADUCTOS" / "PK-1+000.jpg").exists())
            self.assertEqual((base / "Z_other" / "PK-1+000.jpg").read_bytes(), b"DECOY")

    def test_relative_original_restores_to_source_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "VIADUCTOS").mkdir()
            (base / "sub_a").mkdir()
            (base / "VIADUCTOS" / "PK-1+000.jpg").write_bytes(b"X")

            summary = undo_rename_operations(
                base, [("VIADUCTOS/PK-1+000.jpg", "sub_a/DJI_0001.jpg")]
            )
            self.assertEqual(summary["ok"], 1)
            self.assertTrue((base / "sub_a" / "DJI_0001.jpg").is_file())
            self.assertFalse((base / "VIADUCTOS" / "PK-1+000.jpg").exists())

    def test_relative_mapping_key_uses_forward_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            nested = base / "VIADUCTOS" / "a.jpg"
            nested.parent.mkdir()
            nested.write_bytes(b"1")
            self.assertEqual(relative_mapping_key(nested, base), "VIADUCTOS/a.jpg")

    def test_save_rename_report_is_atomic_on_write_failure(self) -> None:
        from unittest import mock

        from src.core.rename_report import save_rename_report

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            good = folder / RENAME_REPORT_FILENAME
            with open(good, "w", encoding="utf-8-sig", newline="") as handle:
                handle.write("original,nuevo,pk,distancia\nkeep.jpg,keep2.jpg,1,1\n")
            before = good.read_bytes()

            real_open = open

            def boom(path, mode="r", *args, **kwargs):
                if str(path).endswith(".__tmp__") and "w" in mode:
                    raise OSError("disk full")
                return real_open(path, mode, *args, **kwargs)

            with mock.patch("builtins.open", boom):
                with self.assertRaises(OSError):
                    save_rename_report(
                        folder,
                        [{"original": "a.jpg", "nuevo": "b.jpg", "pk": "1", "distancia": "1"}],
                    )
            self.assertEqual(good.read_bytes(), before)
            leftovers = list(folder.glob("*.__tmp__"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
