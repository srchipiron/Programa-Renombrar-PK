"""Integration tests for the rename pipeline (process_images)."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.core.models import PhotoItem
from src.core.rename_report import report_csv_path
from src.core.renamer_logic import RenamerLogic


class _DummySpatialCalculator:
    project_axis = None

    def find_nearest_pk_name(self, lat, lon):
        return "PK-1+000", 5.0

    def calculate_pk(self, lat, lon):
        return 1000.0

    def get_landmark_folder(self, name):
        return None

    def is_landmark_name(self, name):
        return False


class TestProcessImagesIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.logic = RenamerLogic(_DummySpatialCalculator())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_jpeg(self, name: str) -> str:
        path = os.path.join(self.folder, name)
        Image.new("RGB", (4, 4), color=(10, 20, 30)).save(path, format="JPEG")
        return path

    def test_process_images_renames_with_backup(self) -> None:
        path = self._write_jpeg("DJI_001.jpg")
        item = PhotoItem(
            path=path,
            name="DJI_001.jpg",
            lat=40.0,
            lon=-3.0,
            date_str="20260601",
            time_str="120000",
            nearest_name="PK-1+000",
            distance=5.0,
            pk_value=1000.0,
            is_inside_threshold=True,
            new_name_base="PK-1+000-[PK]",
        )
        progress: list[tuple[int, int, str]] = []

        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=True,
            progress_cb=lambda d, t, m: progress.append((d, t, m)),
            check_cancel=lambda: False,
        )

        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["errors"], 0)
        renamed = self.folder + os.sep + "PK-1+000-[PK].jpg"
        self.assertTrue(os.path.isfile(renamed))
        self.assertFalse(os.path.isfile(path))
        backup = os.path.join(self.folder, "_backup_originales", "DJI_001.jpg")
        self.assertTrue(os.path.isfile(backup))
        self.assertTrue(report_csv_path(self.folder).is_file())

    def test_process_images_skips_existing_target(self) -> None:
        existing = self._write_jpeg("PK-1+000-[PK].jpg")
        path = self._write_jpeg("DJI_002.jpg")
        item = PhotoItem(
            path=path,
            name="DJI_002.jpg",
            lat=40.0,
            lon=-3.0,
            distance=5.0,
            pk_value=1000.0,
            is_inside_threshold=True,
            new_name_base="PK-1+000-[PK]",
        )
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=False,
            progress_cb=lambda d, t, m: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["ok"], 0)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.path.isfile(existing))


if __name__ == "__main__":
    unittest.main()
