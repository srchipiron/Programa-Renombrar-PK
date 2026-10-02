"""Names from the client's KML meeting a Windows filesystem.

Landmark folders are named by the client (ADR-010) and the operator only
finds out at rename time, over SMB, on a delivery. These cases were all
reproduced before being fixed.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from src.core.models import PhotoItem
from src.core.renamer_logic import (
    RenamerLogic,
    _sanitize_filename_fragment,
    names_same_file,
    safe_join_under,
)


class _Calc:
    """Spatial calculator whose landmark name comes from the client's KML."""

    project_axis = None

    def __init__(self, landmark=None):
        self.landmark = landmark

    def find_nearest_pk_name(self, lat, lon):
        return (self.landmark or "PK-1+000"), 5.0

    def calculate_pk(self, lat, lon):
        return 1000.0

    def get_landmark_folder(self, name):
        return f"VERTEDEROS/{name}" if self.landmark else None

    def is_landmark_name(self, name):
        return bool(self.landmark) and name == self.landmark


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = self.tmp.name

    def _photo(self, nombre: str, nearest: str = "PK-1+000") -> PhotoItem:
        ruta = os.path.join(self.folder, nombre)
        Image.new("RGB", (8, 8), (10, 20, 30)).save(ruta, format="JPEG")
        return PhotoItem(
            path=ruta, name=nombre, lat=40.0, lon=-3.0,
            date_str="20260601", time_str="120000", nearest_name=nearest,
            distance=5.0, pk_value=1000.0, is_inside_threshold=True,
        )

    def _rename(self, logic: RenamerLogic, items, template="-AGO26"):
        items = logic.build_preview_names(items, 50.0, template)
        logic.assign_destination_folders(items, self.folder)
        return logic.process_images(
            items, self.folder, create_backup=False,
            progress_cb=lambda d, t, m: None, check_cancel=lambda: False,
        )

    def _tree(self):
        salida = []
        for raiz, _, ficheros in os.walk(self.folder):
            for f in ficheros:
                if f.lower().endswith(".jpg"):
                    salida.append(
                        os.path.relpath(os.path.join(raiz, f), self.folder).replace("\\", "/")
                    )
        return sorted(salida)


class CaseOnlyRenameTests(_Base):
    """DJI writes .JPG; the plan always lowercases the extension.

    Windows is case-insensitive, so os.path.exists said the destination was
    already taken — by the very file being renamed. The photo was skipped
    with "Destino ya existe", which was not true, and kept its old name.
    """

    def test_a_jpg_to_jpg_rename_is_not_a_collision(self) -> None:
        logic = RenamerLogic(_Calc())
        stats = self._rename(logic, [self._photo("PK-1+000-AGO26.JPG")])

        self.assertEqual(stats["skipped"], 0)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(self._tree(), ["PK-1+000-AGO26.jpg"])

    def test_the_confirm_dialog_agrees_with_the_rename(self) -> None:
        """get_rename_plan feeds the F7 dialog and had the same comparison."""
        logic = RenamerLogic(_Calc())
        items = logic.build_preview_names([self._photo("PK-1+000-AGO26.JPG")], 50.0, "-AGO26")
        plan = logic.get_rename_plan(items, self.folder)

        self.assertEqual(plan["conflicts"], 0)
        self.assertEqual(plan["effective"], 1)

    def test_a_real_collision_is_still_a_collision(self) -> None:
        logic = RenamerLogic(_Calc())
        ocupante = self._photo("PK-1+000-AGO26.jpg")   # ya ocupa el destino
        entrante = self._photo("DJI_001.JPG")
        stats = self._rename(logic, [entrante])

        self.assertEqual(stats["skipped"], 1)
        self.assertEqual(stats["ok"], 0)
        self.assertTrue(os.path.exists(ocupante.path))


class NamesSameFileTests(unittest.TestCase):
    def test_identical_strings(self) -> None:
        self.assertTrue(names_same_file("a/b.jpg", "a/b.jpg"))

    def test_empty_is_never_the_same_file(self) -> None:
        self.assertFalse(names_same_file("", "a.jpg"))
        self.assertFalse(names_same_file("a.jpg", ""))

    def test_different_files_are_different(self) -> None:
        self.assertFalse(names_same_file("a.jpg", "b.jpg"))

    @unittest.skipUnless(os.name == "nt", "regla de Windows")
    def test_case_differs_only_on_a_case_insensitive_filesystem(self) -> None:
        self.assertTrue(names_same_file("FOTO.JPG", "foto.jpg"))


class LandmarkFolderTests(_Base):
    """The vertedero folder is named by whoever wrote the KML."""

    def test_a_colon_in_the_name_does_not_kill_the_batch(self) -> None:
        """os.makedirs raised WinError 267 and it escaped process_images."""
        logic = RenamerLogic(_Calc(landmark="TP:01"))
        stats = self._rename(logic, [self._photo("DJI_001.JPG", "TP:01")])

        self.assertEqual(stats["errors"], 0)
        self.assertEqual(stats["ok"], 1)
        self.assertEqual(self._tree(), ["VERTEDEROS/TP_01/PK-TP01-AGO26.jpg"])

    def test_every_character_windows_rejects_is_replaced(self) -> None:
        for malo in ':*?"<>|':
            with self.subTest(caracter=malo):
                destino = safe_join_under(self.folder, f"VERTEDEROS/TP{malo}01")
                self.assertIsNotNone(destino)
                self.assertNotIn(malo, os.path.basename(destino))
                os.makedirs(destino, exist_ok=True)   # no debe lanzar

    def test_a_trailing_space_or_dot_is_dropped_by_us_not_by_windows(self) -> None:
        """Windows strips them silently, so our path stopped matching disk."""
        for nombre in ("TP-01 ", "TP-01."):
            with self.subTest(nombre=nombre):
                destino = safe_join_under(self.folder, f"VERTEDEROS/{nombre}")
                self.assertEqual(os.path.basename(destino), "TP-01")

    def test_a_reserved_device_name_is_escaped(self) -> None:
        """makedirs('NUL') reports success and creates nothing."""
        destino = safe_join_under(self.folder, "VERTEDEROS/NUL")
        self.assertEqual(os.path.basename(destino), "_NUL")
        os.makedirs(destino, exist_ok=True)
        self.assertTrue(os.path.isdir(destino))

    def test_traversal_is_still_refused(self) -> None:
        """Sanitising must not have opened the door the guards close."""
        self.assertIsNone(safe_join_under(self.folder, "VERTEDEROS/../../fuera"))
        self.assertIsNone(safe_join_under(self.folder, "../fuera"))
        self.assertIsNone(safe_join_under(self.folder, "C:/Windows"))


class BatchIsolationTests(_Base):
    """One unusable destination must cost one photo, not the whole delivery."""

    def test_a_failing_makedirs_is_one_error_and_the_rest_still_run(self) -> None:
        logic = RenamerLogic(_Calc())
        items = [self._photo("DJI_001.JPG"), self._photo("DJI_002.JPG")]
        items[1].time_str = "120500"
        items = logic.build_preview_names(items, 50.0, "-AGO26")
        logic.assign_destination_folders(items, self.folder)

        real = os.makedirs
        vistas = {"n": 0}
        objetivo = os.path.normcase(os.path.abspath(self.folder))

        def falla_la_primera_del_lote(path, *a, **kw):
            # Solo la carpeta destino de las fotos, no el andamiaje previo.
            if os.path.normcase(os.path.abspath(path)) == objetivo:
                vistas["n"] += 1
                if vistas["n"] == 1:
                    raise OSError(123, "nombre de directorio no valido")
            return real(path, *a, **kw)

        with patch("src.core.renamer_logic.os.makedirs", side_effect=falla_la_primera_del_lote):
            stats = logic.process_images(
                items, self.folder, create_backup=False,
                progress_cb=lambda d, t, m: None, check_cancel=lambda: False,
            )

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["ok"], 1, "la segunda foto debe procesarse igual")

    def test_an_unusable_landmark_folder_does_not_abort_the_scaffolding(self) -> None:
        """It ran before any photo, so a failure meant zero renamed."""
        logic = RenamerLogic(_Calc(landmark="Gregal"))
        logic.spatial_calc.named_points = []
        real = os.makedirs

        def falla_en_vertederos(path, *a, **kw):
            if "VERTEDEROS" in str(path) and os.path.basename(str(path)) != "VERTEDEROS":
                raise OSError(123, "no se puede crear")
            return real(path, *a, **kw)

        with patch("src.core.renamer_logic.os.makedirs", side_effect=falla_en_vertederos):
            creadas = logic.ensure_work_folders(self.folder, landmark_names=["Gregal"])

        self.assertTrue(any(c.endswith("OTROS") for c in creadas))
        self.assertFalse(any(c.endswith("Gregal") for c in creadas))


class SanitiseTests(unittest.TestCase):
    def test_keeps_accents_and_the_pk_separator(self) -> None:
        self.assertEqual(_sanitize_filename_fragment("PK-1+000 Peñón"), "PK-1+000 Peñón")

    def test_is_bounded(self) -> None:
        self.assertLessEqual(len(_sanitize_filename_fragment("x" * 500)), 120)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
