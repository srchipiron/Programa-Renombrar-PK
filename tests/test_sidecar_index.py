"""Tests for the directory-scoped sidecar index and its rename integration.

The index replaces a per-photo ``os.scandir`` (O(files^2) per folder) with one
listing per directory, reused from the ``os.walk`` analysis already performs.
Behaviour must stay byte-for-byte identical to the old helper.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from src.core.models import PhotoItem
from src.core.renamer_logic import (
    SidecarIndex,
    collect_analysis_image_files,
    collect_analysis_tree,
    find_sidecars,
    RenamerLogic,
)


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


class TestSidecarIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _touch(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_matches_single_shot_helper(self) -> None:
        photo = self._touch("IMG_001.JPG")
        self._touch("IMG_001.DNG")
        self._touch("IMG_001.xmp")
        self._touch("UNRELATED.TXT")
        self._touch("IMG_002.JPG")

        index = SidecarIndex()
        self.assertEqual(
            sorted(index.find(str(photo))),
            sorted(find_sidecars(str(photo))),
        )
        self.assertEqual(
            sorted(Path(p).name.lower() for p in index.find(str(photo))),
            ["img_001.dng", "img_001.xmp"],
        )

    def test_lazy_scan_for_unknown_directory(self) -> None:
        photo = self._touch("sub/IMG_010.JPG")
        self._touch("sub/IMG_010.wav")
        index = SidecarIndex()  # nothing registered up front
        self.assertEqual(
            [Path(p).name for p in index.find(str(photo))], ["IMG_010.wav"]
        )

    def test_missing_directory_is_not_fatal(self) -> None:
        index = SidecarIndex()
        self.assertEqual(index.find(str(self.root / "nope" / "a.jpg")), [])

    def test_forget_picks_up_new_files(self) -> None:
        photo = self._touch("IMG_020.JPG")
        index = SidecarIndex()
        self.assertEqual(index.find(str(photo)), [])
        self._touch("IMG_020.dng")
        self.assertEqual(index.find(str(photo)), [])  # cached listing
        index.forget(str(self.root))
        self.assertEqual([Path(p).name for p in index.find(str(photo))], ["IMG_020.dng"])

    def test_stem_match_is_exact_not_prefix(self) -> None:
        photo = self._touch("DJI_001.JPG")
        self._touch("DJI_0011.dng")
        self._touch("DJI_001_edit.dng")
        index = SidecarIndex()
        self.assertEqual(index.find(str(photo)), [])


class TestCollectAnalysisTree(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _touch(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
        return path

    def test_tree_matches_legacy_listing_and_indexes_sidecars(self) -> None:
        a = self._touch("a.jpg")
        self._touch("a.dng")
        b = self._touch("nested/b.JPG")
        self._touch("nested/b.xmp")
        # Renamer-managed folders must stay pruned in both APIs.
        self._touch("_backup_originales/old.jpg")
        self._touch("VERTEDEROS/x.jpg")

        paths, index = collect_analysis_tree(str(self.root))
        self.assertEqual(sorted(paths), sorted(collect_analysis_image_files(str(self.root))))
        self.assertEqual({Path(p).name for p in paths}, {"a.jpg", "b.JPG"})
        self.assertEqual([Path(p).name for p in index.find(str(a))], ["a.dng"])
        self.assertEqual([Path(p).name for p in index.find(str(b))], ["b.xmp"])

    def test_missing_folder_returns_empty_index(self) -> None:
        paths, index = collect_analysis_tree(str(self.root / "ghost"))
        self.assertEqual(paths, [])
        self.assertEqual(index.find(str(self.root / "ghost" / "a.jpg")), [])


class TestRenameKeepsSidecarsWithoutRescan(unittest.TestCase):
    """``process_images`` must derive the new sidecar list from its own plan."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.logic = RenamerLogic(_DummySpatialCalculator())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _item(self, name: str, base: str) -> PhotoItem:
        path = os.path.join(self.folder, name)
        Image.new("RGB", (4, 4), color=(10, 20, 30)).save(path, format="JPEG")
        stem = os.path.splitext(name)[0]
        dng = os.path.join(self.folder, stem + ".dng")
        Path(dng).write_bytes(b"raw")
        return PhotoItem(
            path=path,
            name=name,
            lat=40.0,
            lon=-3.0,
            date_str="20260601",
            time_str="120000",
            nearest_name="PK-1+000",
            distance=5.0,
            pk_value=1000.0,
            is_inside_threshold=True,
            new_name_base=base,
            sidecars=[dng],
        )

    def test_sidecar_list_follows_the_rename(self) -> None:
        item = self._item("DJI_001.jpg", "PK-1+000-A")
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=False,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 1)
        expected = os.path.join(self.folder, "PK-1+000-A.dng")
        self.assertTrue(os.path.isfile(expected))
        self.assertEqual(item.sidecars, [expected])
        # Equivalent to what a fresh directory scan would report.
        self.assertEqual(sorted(item.sidecars), sorted(find_sidecars(item.path)))

    def test_sidecar_already_at_destination_is_kept(self) -> None:
        """A companion whose name already matches the target must not be lost."""
        item = self._item("PK-1+000-B.jpg", "PK-1+000-B")
        sidecar = item.sidecars[0]
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=False,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(item.sidecars, [sidecar])
        self.assertTrue(os.path.isfile(sidecar))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
