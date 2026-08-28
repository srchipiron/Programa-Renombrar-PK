"""Tests for the SQLite undo history layer."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.ui_qt.undo_history import UndoHistory, apply_undo


class TestUndoHistory(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "undo.sqlite"
        self.history = UndoHistory(self.db_path)
        self.folder = Path(self.temp_dir) / "photos"
        self.folder.mkdir()

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_latest_for_folder_returns_most_recent(self) -> None:
        recorded = self.history.record(str(self.folder), {"new_a.jpg": "old_a.jpg"})
        self.assertGreater(recorded, 0)
        entry = self.history.latest_for_folder(str(self.folder))
        self.assertIsNotNone(entry)
        self.assertEqual(entry.total, 1)
        self.assertEqual(entry.mapping["new_a.jpg"], "old_a.jpg")

    def test_apply_undo_restores_files(self) -> None:
        renamed = self.folder / "PK-1-001.jpg"
        renamed.write_bytes(b"x")
        entry = self.history.record(
            str(self.folder),
            {"PK-1-001.jpg": "original.jpg"},
        )
        self.assertGreater(entry, 0)

        latest = self.history.latest_for_folder(str(self.folder))
        self.assertIsNotNone(latest)
        summary = apply_undo(latest)
        self.assertEqual(summary["ok"], 1)
        self.assertTrue((self.folder / "original.jpg").exists())
        self.assertFalse(renamed.exists())

    def test_apply_undo_uses_relative_path_not_first_basename_match(self) -> None:
        """Same basename in two folders: only the mapped relative path is undone."""
        first = self.folder / "A_first"
        second = self.folder / "Z_second"
        first.mkdir()
        second.mkdir()
        (first / "PK-1+000.jpg").write_bytes(b"WRONG")
        (second / "PK-1+000.jpg").write_bytes(b"RIGHT")

        # process_images stores relative originals when the source was nested.
        self.history.record(
            str(self.folder),
            {"Z_second/PK-1+000.jpg": "Z_second/shot_b.jpg"},
        )
        latest = self.history.latest_for_folder(str(self.folder))
        summary = apply_undo(latest)
        self.assertEqual(summary["ok"], 1)
        self.assertTrue((second / "shot_b.jpg").is_file())
        self.assertEqual((second / "shot_b.jpg").read_bytes(), b"RIGHT")
        self.assertTrue((first / "PK-1+000.jpg").is_file())
        self.assertEqual((first / "PK-1+000.jpg").read_bytes(), b"WRONG")


class TestUndoHistoryDefaultPath(unittest.TestCase):
    """Regression test: the default SQLite path must be absolute (project root).

    Before the fix UndoHistory() used ``Path("logs") / "undo_history.sqlite"``
    which resolved against the current working directory.  If the user launched
    the exe from the Desktop the history file ended up there instead of next to
    main.py, losing history on every launch from a different directory.
    """

    def test_default_db_path_is_absolute(self) -> None:
        from src.ui_qt.undo_history import _DEFAULT_DB_PATH
        self.assertTrue(
            _DEFAULT_DB_PATH.is_absolute(),
            f"_DEFAULT_DB_PATH must be absolute, got: {_DEFAULT_DB_PATH}",
        )

    def test_default_db_path_inside_project_logs(self) -> None:
        from src.ui_qt.undo_history import _DEFAULT_DB_PATH, _PROJECT_ROOT
        # The DB must live under <project>/logs/
        self.assertEqual(_DEFAULT_DB_PATH.parent, _PROJECT_ROOT / "logs")
        self.assertEqual(_DEFAULT_DB_PATH.name, "undo_history.sqlite")

    def test_sqlite_timeout_is_set(self) -> None:
        """sqlite3.connect must use a timeout so a brief lock doesn't crash."""
        import inspect, sqlite3
        from src.ui_qt import undo_history as uh_mod
        src = inspect.getsource(uh_mod.UndoHistory._connect)
        self.assertIn("timeout=5", src)


if __name__ == "__main__":
    unittest.main()
