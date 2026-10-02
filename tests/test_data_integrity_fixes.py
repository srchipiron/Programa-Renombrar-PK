"""Regression tests for data-integrity fixes (XMP, cancel, landmarks, session)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from src.core.models import PhotoItem
from src.core.orientation import extract_jpeg_xmp_packet, inject_jpeg_xmp_packet
from src.core.rename_report import load_rename_mapping
from src.core.renamer_logic import RenamerLogic
from src.core.spatial_calculator import SpatialCalculator
from src.ui_qt.session_store import DEFAULT_SESSION_PATH


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


def _jpeg(folder: str, name: str) -> str:
    path = os.path.join(folder, name)
    Image.new("RGB", (8, 8), color=(40, 50, 60)).save(path, format="JPEG")
    return path


def _photo(path: str, base: str) -> PhotoItem:
    return PhotoItem(
        path=path,
        name=os.path.basename(path),
        lat=40.0,
        lon=-3.0,
        date_str="20260801",
        time_str="120000",
        nearest_name="PK-1+000",
        distance=5.0,
        pk_value=1000.0,
        is_inside_threshold=True,
        new_name_base=base,
    )


class TestAtomicXmpInject(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = _jpeg(self.tmp.name, "with_xmp.jpg")
        payload = (
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description xmlns:drone-dji="http://www.dji.com/drone/1.0/" '
            b'drone-dji:GimbalYawDegree="+10.0"/>'
            b"</rdf:RDF></x:xmpmeta>"
        )
        self.segment = (
            b"\xff\xe1"
            + (len(payload) + 2 + 29).to_bytes(2, "big")
            + b"http://ns.adobe.com/xap/1.0/\x00"
            + payload
        )
        self.assertTrue(inject_jpeg_xmp_packet(self.path, self.segment))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_inject_is_atomic_on_write_failure(self) -> None:
        before = Path(self.path).read_bytes()
        self.assertGreater(len(before), 100)

        real_open = open

        def boom(path, mode="r", *args, **kwargs):
            # Fail only the temp write so the live JPEG is never truncated.
            if str(path).endswith(".__xmp_tmp__") and "w" in mode:
                raise OSError("disk full")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", boom):
            ok = inject_jpeg_xmp_packet(self.path, self.segment)
        self.assertFalse(ok)
        after = Path(self.path).read_bytes()
        self.assertEqual(after, before)
        self.assertFalse(os.path.exists(self.path + ".__xmp_tmp__"))
        self.assertIsNotNone(extract_jpeg_xmp_packet(self.path))


class TestProcessImagesIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = self.tmp.name
        self.logic = RenamerLogic(_DummySpatialCalculator())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_cancel_records_completed_renames_in_mapping(self) -> None:
        items = []
        for i in range(3):
            path = _jpeg(self.folder, f"src_{i}.jpg")
            items.append(_photo(path, f"PK-1+00{i}"))

        # Cancel after the first successful job has been accounted for.
        state = {"seen_ok": 0}

        def check_cancel() -> bool:
            return state["seen_ok"] >= 1

        def progress(done, total, msg):
            if "Procesando" in msg:
                state["seen_ok"] += 1

        stats = self.logic.process_images(
            items,
            self.folder,
            create_backup=False,
            progress_cb=progress,
            check_cancel=check_cancel,
        )
        self.assertGreaterEqual(stats["ok"], 1)
        self.assertGreater(stats["cancelled"], 0)
        self.assertEqual(len(stats["mapping"]), stats["ok"])
        mapping = load_rename_mapping(self.folder)
        self.assertEqual(len(mapping), stats["ok"])

    def test_updates_photoitem_path_after_rename(self) -> None:
        path = _jpeg(self.folder, "orig.jpg")
        item = _photo(path, "PK-9+000")
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=False,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(item.name, "PK-9+000.jpg")
        self.assertTrue(item.path.endswith("PK-9+000.jpg"))
        self.assertTrue(os.path.isfile(item.path))
        self.assertFalse(os.path.isfile(path))

    def test_skip_does_not_create_backup(self) -> None:
        _jpeg(self.folder, "PK-1+000.jpg")
        path = _jpeg(self.folder, "dup.jpg")
        item = _photo(path, "PK-1+000")
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=True,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["skipped"], 1)
        backup_root = os.path.join(self.folder, "_backup_originales")
        if os.path.isdir(backup_root):
            leftovers = [
                f for f in Path(backup_root).rglob("*") if f.is_file() and f.name != "Thumbs.db"
            ]
            self.assertEqual(leftovers, [])

    def test_sidecar_pairs_recorded_in_mapping(self) -> None:
        path = _jpeg(self.folder, "shot.jpg")
        sidecar = os.path.join(self.folder, "shot.xmp")
        Path(sidecar).write_text("<xmp/>", encoding="utf-8")
        item = _photo(path, "PK-7+000")
        item.sidecars = [sidecar]
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=False,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(stats["mapping"]["PK-7+000.jpg"], "shot.jpg")
        self.assertEqual(stats["mapping"]["PK-7+000.xmp"], "shot.xmp")
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "PK-7+000.xmp")))
        self.assertFalse(os.path.isfile(sidecar))

    def test_metadata_failure_rolls_back_rename(self) -> None:
        path = _jpeg(self.folder, "orig_meta.jpg")
        item = _photo(path, "PK-3+000")
        with mock.patch.object(self.logic, "write_metadata", return_value=False):
            stats = self.logic.process_images(
                [item],
                self.folder,
                create_backup=False,
                progress_cb=lambda *a: None,
                check_cancel=lambda: False,
            )
        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["ok"], 0)
        self.assertEqual(stats.get("mapping") or {}, {})
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.isfile(os.path.join(self.folder, "PK-3+000.jpg")))
        self.assertEqual(item.name, "orig_meta.jpg")
        self.assertEqual(item.path, path)

    def test_metadata_failure_records_mapping_when_rollback_fails(self) -> None:
        path = _jpeg(self.folder, "stuck2.jpg")
        item = _photo(path, "PK-4+100")
        real_rename = os.rename
        renamed = {"done": False}

        def forward_only_rename(src, dst):
            if os.path.basename(src) == "stuck2.jpg":
                real_rename(src, dst)
                renamed["done"] = True
                return
            raise OSError("no rollback")

        with mock.patch.object(self.logic, "write_metadata", return_value=False):
            with mock.patch("src.core.renamer_logic.os.rename", side_effect=forward_only_rename):
                with mock.patch("src.core.renamer_logic._try_rename", return_value=False):
                    stats = self.logic.process_images(
                        [item],
                        self.folder,
                        create_backup=False,
                        progress_cb=lambda *a: None,
                        check_cancel=lambda: False,
                    )
        self.assertEqual(stats["errors"], 1)
        self.assertTrue(renamed["done"])
        self.assertIn("PK-4+100.jpg", stats["mapping"])
        self.assertEqual(stats["mapping"]["PK-4+100.jpg"], "stuck2.jpg")
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "PK-4+100.jpg")))
        self.assertFalse(os.path.isfile(path))
        self.assertEqual(item.name, "PK-4+100.jpg")

    def test_stuck_metadata_moves_sidecars_and_records_them(self) -> None:
        path = _jpeg(self.folder, "stuck_sc.jpg")
        sidecar = os.path.join(self.folder, "stuck_sc.xmp")
        Path(sidecar).write_text("<xmp/>", encoding="utf-8")
        item = _photo(path, "PK-6+600")
        item.sidecars = [sidecar]
        real_rename = os.rename

        def forward_photo_only(src, dst):
            if os.path.basename(src) == "stuck_sc.jpg":
                real_rename(src, dst)
                return
            raise OSError("no photo rollback")

        def try_rename_sidecars_ok(src, dst):
            # Photo rollback fails; sidecar moves succeed.
            if os.path.basename(src) == "PK-6+600.jpg":
                return False
            try:
                if os.path.exists(dst):
                    return False
                real_rename(src, dst)
                return True
            except OSError:
                return False

        with mock.patch.object(self.logic, "write_metadata", return_value=False):
            with mock.patch("src.core.renamer_logic.os.rename", side_effect=forward_photo_only):
                with mock.patch(
                    "src.core.renamer_logic._try_rename", side_effect=try_rename_sidecars_ok
                ):
                    stats = self.logic.process_images(
                        [item],
                        self.folder,
                        create_backup=False,
                        progress_cb=lambda *a: None,
                        check_cancel=lambda: False,
                    )
        self.assertEqual(stats["errors"], 1)
        self.assertIn("PK-6+600.jpg", stats["mapping"])
        self.assertEqual(stats["mapping"].get("PK-6+600.xmp"), "stuck_sc.xmp")
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "PK-6+600.jpg")))
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "PK-6+600.xmp")))
        self.assertFalse(os.path.isfile(sidecar))

    def test_sidecar_destination_collision_skips_without_orphaning(self) -> None:
        path = _jpeg(self.folder, "pair.jpg")
        sidecar = os.path.join(self.folder, "pair.xmp")
        Path(sidecar).write_text("<xmp/>", encoding="utf-8")
        # Occupied sidecar target next to the planned photo name.
        Path(os.path.join(self.folder, "PK-8+000.xmp")).write_text("<busy/>", encoding="utf-8")
        item = _photo(path, "PK-8+000")
        item.sidecars = [sidecar]
        stats = self.logic.process_images(
            [item],
            self.folder,
            create_backup=True,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["ok"], 0)
        self.assertTrue(os.path.isfile(path), "photo must stay put")
        self.assertTrue(os.path.isfile(sidecar), "sidecar must stay put")
        self.assertFalse(os.path.isfile(os.path.join(self.folder, "PK-8+000.jpg")))
        backup_root = os.path.join(self.folder, "_backup_originales")
        if os.path.isdir(backup_root):
            leftovers = [
                f for f in Path(backup_root).rglob("*") if f.is_file() and f.name != "Thumbs.db"
            ]
            self.assertEqual(leftovers, [])

    def test_get_rename_plan_counts_sidecar_conflicts(self) -> None:
        path = _jpeg(self.folder, "plan.jpg")
        sidecar = os.path.join(self.folder, "plan.xmp")
        Path(sidecar).write_text("<xmp/>", encoding="utf-8")
        Path(os.path.join(self.folder, "PK-5+000.xmp")).write_text("<busy/>", encoding="utf-8")
        item = _photo(path, "PK-5+000")
        item.sidecars = [sidecar]
        plan = self.logic.get_rename_plan([item], self.folder)
        self.assertEqual(plan["total"], 1)
        self.assertEqual(plan["conflicts"], 1)
        self.assertEqual(plan["sidecar_conflicts"], 1)
        self.assertEqual(plan["photo_conflicts"], 0)
        self.assertEqual(plan["effective"], 0)

    def test_backup_preserves_same_basename_from_different_source_dirs(self) -> None:
        """Two DJI_0001.jpg collapsing into one dest folder must both stay in backup."""

        class _LandmarkSpatial(_DummySpatialCalculator):
            def get_landmark_folder(self, name):
                return "VIADUCTOS"

            def is_landmark_name(self, name):
                return True

        logic = RenamerLogic(_LandmarkSpatial())
        os.makedirs(os.path.join(self.folder, "sub_a"))
        os.makedirs(os.path.join(self.folder, "sub_b"))
        p1 = os.path.join(self.folder, "sub_a", "DJI_0001.jpg")
        p2 = os.path.join(self.folder, "sub_b", "DJI_0001.jpg")
        Image.new("RGB", (8, 8), color=(10, 20, 30)).save(p1, format="JPEG")
        Image.new("RGB", (8, 8), color=(200, 100, 50)).save(p2, format="JPEG")
        bytes_a = Path(p1).read_bytes()
        bytes_b = Path(p2).read_bytes()
        self.assertNotEqual(bytes_a, bytes_b)
        items = [
            _photo(p1, "VIADUCTO_X"),
            _photo(p2, "VIADUCTO_X"),
        ]
        items[0].nearest_name = "Viaducto X"
        items[1].nearest_name = "Viaducto X"
        items[1].time_str = "120100"
        stats = logic.process_images(
            items,
            self.folder,
            create_backup=True,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 2)
        b1 = Path(self.folder) / "_backup_originales" / "sub_a" / "DJI_0001.jpg"
        b2 = Path(self.folder) / "_backup_originales" / "sub_b" / "DJI_0001.jpg"
        self.assertTrue(b1.is_file(), f"missing {b1}")
        self.assertTrue(b2.is_file(), f"missing {b2}")
        self.assertEqual(b1.read_bytes(), bytes_a)
        self.assertEqual(b2.read_bytes(), bytes_b)

    def test_cross_dir_rename_mapping_and_csv_undo_restore_to_root(self) -> None:
        class _ViaductSpatial(_DummySpatialCalculator):
            def get_landmark_folder(self, name):
                return "VIADUCTOS"

            def is_landmark_name(self, name):
                return False

        logic = RenamerLogic(_ViaductSpatial())
        path = _jpeg(self.folder, "src.jpg")
        os.makedirs(os.path.join(self.folder, "Z_other"))
        Path(self.folder, "Z_other", "PK-9+999.jpg").write_bytes(b"DECOY")
        item = _photo(path, "PK-9+999")
        stats = logic.process_images(
            [item],
            self.folder,
            create_backup=False,
            progress_cb=lambda *a: None,
            check_cancel=lambda: False,
        )
        self.assertEqual(stats["ok"], 1)
        self.assertIn("VIADUCTOS/PK-9+999.jpg", stats["mapping"])
        self.assertEqual(stats["mapping"]["VIADUCTOS/PK-9+999.jpg"], "src.jpg")
        ok, msg = logic.undo_last_rename_from_csv(self.folder)
        self.assertTrue(ok, msg)
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.isfile(os.path.join(self.folder, "VIADUCTOS", "PK-9+999.jpg")))
        self.assertFalse(os.path.isfile(os.path.join(self.folder, "VIADUCTOS", "src.jpg")))
        self.assertEqual(
            Path(self.folder, "Z_other", "PK-9+999.jpg").read_bytes(), b"DECOY"
        )


class TestAtomicExifInsert(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = _jpeg(self.tmp.name, "atomic.jpg")
        self.logic = RenamerLogic(_DummySpatialCalculator())
        # Seed XMP so the write path exercises EXIF+XMP promotion.
        payload = (
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description xmlns:drone-dji="http://www.dji.com/drone/1.0/" '
            b'drone-dji:GimbalYawDegree="+10.0"/>'
            b"</rdf:RDF></x:xmpmeta>"
        )
        segment = (
            b"\xff\xe1"
            + (len(payload) + 2 + 29).to_bytes(2, "big")
            + b"http://ns.adobe.com/xap/1.0/\x00"
            + payload
        )
        self.assertTrue(inject_jpeg_xmp_packet(self.path, segment))
        self.before = Path(self.path).read_bytes()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exif_temp_write_failure_preserves_live_jpeg(self) -> None:
        real_open = open

        def boom(path, mode="r", *args, **kwargs):
            if str(path).endswith(".__exif_tmp__") and "w" in mode:
                raise OSError("disk full")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("builtins.open", boom):
            ok = self.logic.write_metadata(self.path, "PK-1+000")
        self.assertFalse(ok)
        after = Path(self.path).read_bytes()
        self.assertEqual(after, self.before)
        self.assertFalse(os.path.exists(self.path + ".__exif_tmp__"))
        self.assertIsNotNone(extract_jpeg_xmp_packet(self.path))

    def test_write_metadata_success_preserves_xmp_and_sets_comment(self) -> None:
        import piexif

        ok = self.logic.write_metadata(self.path, "PK-9+999-TEST")
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.path + ".__exif_tmp__"))
        xmp = extract_jpeg_xmp_packet(self.path)
        self.assertIsNotNone(xmp)
        self.assertIn(b"drone-dji:GimbalYawDegree", xmp)
        exif = piexif.load(self.path)
        comment = exif.get("Exif", {}).get(piexif.ExifIFD.UserComment)
        self.assertIsNotNone(comment)

class TestLandmarkOutsideRadius(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_landmark_outside_capture_radius_does_not_beat_pk(self) -> None:
        lat0, lon0 = 37.80, -0.96
        path = os.path.join(self.tmp.name, "pts.geojson")
        payload = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[lon0, lat0], [lon0, lat0 + 0.01]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {"name": "20+000"},
                    "geometry": {"type": "Point", "coordinates": [lon0, lat0]},
                },
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

        calc = SpatialCalculator()
        calc.load_kml(path)
        calc.set_landmark_capture_radius(50.0)
        # Landmark ~333 m north of the PK.
        calc.add_landmarks_from_dicts(
            [{"name": "FarLM", "lat": lat0 + 0.003, "lon": lon0}]
        )
        # Query ~55 m from the landmark (outside 50 m capture) but still
        # geometrically nearer to FarLM than to the PK — STRtree would pick
        # FarLM without the non-landmark fallback.
        name, dist = calc.find_nearest_pk_name(lat0 + 0.0025, lon0)
        self.assertEqual(name, "20+000")
        self.assertGreater(dist, 50.0)


class TestSessionDefaultPath(unittest.TestCase):
    def test_default_session_path_is_absolute_under_the_data_logs(self) -> None:
        """Never relative to the working directory the shortcut launched from.

        The folder itself moved: state now lives in the app's data directory
        (next to the executable, or %LOCALAPPDATA% for a read-only install),
        which is what lets an installed copy save at all.
        """
        from src.core.paths import logs_dir

        self.assertTrue(DEFAULT_SESSION_PATH.is_absolute())
        self.assertEqual(DEFAULT_SESSION_PATH.parent, logs_dir())
        self.assertEqual(DEFAULT_SESSION_PATH.name, "last_session.json")


class TestConfigSetSettingValidation(unittest.TestCase):
    def test_set_setting_rejects_invalid_threshold(self) -> None:
        from src.core.config import ConfigManager

        with tempfile.TemporaryDirectory() as tmp:
            mgr = ConfigManager(os.path.join(tmp, "config.json"))
            with self.assertRaises(ValueError):
                mgr.set_setting("threshold", -1.0)


if __name__ == "__main__":
    unittest.main()
