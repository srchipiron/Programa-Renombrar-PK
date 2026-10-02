"""Tests for the Qt-free session autosave/restore logic."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.models import PhotoItem
from src.ui_qt.session_store import SessionStore


class TestSessionStore(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.tmp.name) / "session.json")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_photo(self, name: str) -> PhotoItem:
        path = Path(self.tmp.name) / name
        path.write_bytes(b"x")
        return PhotoItem(path=str(path), name=name, lat=1.0, lon=2.0)

    def test_save_with_no_items_is_noop(self) -> None:
        self.store.save("folder", "kml.kml", [])
        self.assertFalse(self.store.path.exists())

    def test_round_trip_save_and_load(self) -> None:
        photo = self._make_photo("a.jpg")
        self.store.save("/some/folder", "/some/axis.kml", [photo])

        loaded = self.store.load()
        self.assertEqual(loaded["folder"], "/some/folder")
        self.assertEqual(loaded["kml"], "/some/axis.kml")
        self.assertEqual(loaded["restored_count"], 1)
        self.assertEqual(loaded["total_count"], 1)
        self.assertEqual(loaded["items"][0].name, "a.jpg")

    def test_load_missing_file_returns_empty_dict(self) -> None:
        self.assertEqual(self.store.load(), {})

    def test_load_filters_out_deleted_files(self) -> None:
        photo = self._make_photo("b.jpg")
        self.store.save("/folder", "/axis.kml", [photo])
        Path(photo.path).unlink()

        self.assertEqual(self.store.load(), {})

    def test_load_partial_restore_when_some_files_missing(self) -> None:
        kept = self._make_photo("kept.jpg")
        gone = self._make_photo("gone.jpg")
        self.store.save("/folder", "/axis.kml", [kept, gone])
        Path(gone.path).unlink()

        loaded = self.store.load()
        self.assertEqual(loaded["restored_count"], 1)
        self.assertEqual(loaded["total_count"], 2)
        self.assertEqual(loaded["items"][0].name, "kept.jpg")

    def test_load_corrupt_json_returns_empty_dict(self) -> None:
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text("not valid json", encoding="utf-8")
        self.assertEqual(self.store.load(), {})

    def test_load_tolerates_unknown_fields_from_older_sessions(self) -> None:
        photo = self._make_photo("c.jpg")
        self.store.save("/folder", "/axis.kml", [photo])
        raw = self.store.path.read_text(encoding="utf-8")
        # Simulate an older session payload with a field removed since.
        raw = raw.replace('"name": "c.jpg"', '"name": "c.jpg", "legacy_field": 123')
        self.store.path.write_text(raw, encoding="utf-8")

        loaded = self.store.load()
        self.assertEqual(loaded["items"][0].name, "c.jpg")


if __name__ == "__main__":
    unittest.main()
