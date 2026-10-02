"""The one thumbnail reader, shared by the preview pane and the map.

They used to have a copy each. The copies drifted, and the preview pane
silently stopped rotating anything that was not a JPEG.
"""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

import piexif
from PIL import Image

from src.core.images import MAX_PIXELS, load_thumbnail


class ThumbnailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _jpeg(self, name="foto.jpg", size=(1200, 800), orientation=None) -> Path:
        ruta = Path(self.tmp.name) / name
        kwargs = {}
        if orientation is not None:
            kwargs["exif"] = piexif.dump(
                {"0th": {piexif.ImageIFD.Orientation: orientation},
                 "Exif": {}, "GPS": {}, "1st": {}}
            )
        Image.new("RGB", size, (40, 90, 140)).save(ruta, "JPEG", **kwargs)
        return ruta

    def test_fits_inside_the_requested_box(self) -> None:
        img = load_thumbnail(str(self._jpeg()), 360)
        self.assertIsNotNone(img)
        self.assertLessEqual(max(img.size), 360)
        self.assertEqual(img.mode, "RGB")

    def test_the_result_outlives_the_open_file(self) -> None:
        """It is returned from inside a `with`; it must not be lazy."""
        img = load_thumbnail(str(self._jpeg()), 360)
        # Reading a pixel forces the decode: a lazy image would raise here
        # because the file is already closed. JPEG is lossy, hence the margin.
        for leido, esperado in zip(img.getpixel((0, 0))[:3], (40, 90, 140)):
            self.assertAlmostEqual(leido, esperado, delta=4)

    def test_a_rotated_photo_comes_back_upright(self) -> None:
        ruta = self._jpeg("girada.jpg", size=(1200, 800), orientation=6)
        img = load_thumbnail(str(ruta), 360)
        # Orientation 6 means the camera was held on its side: the thumbnail
        # must come out taller than it is wide.
        self.assertGreater(img.height, img.width)

    def test_a_photo_without_orientation_is_left_alone(self) -> None:
        img = load_thumbnail(str(self._jpeg(size=(1200, 800))), 360)
        self.assertGreater(img.width, img.height)

    def test_png_is_handled_too(self) -> None:
        """The private _getexif() did not exist here; the pane showed nothing."""
        ruta = Path(self.tmp.name) / "captura.png"
        Image.new("RGB", (600, 400), (10, 10, 10)).save(ruta, "PNG")
        self.assertIsNotNone(load_thumbnail(str(ruta), 360))

    def test_a_broken_file_returns_none_and_says_why(self) -> None:
        """A blank preview has to leave a trace, not vanish."""
        ruta = Path(self.tmp.name) / "rota.jpg"
        ruta.write_bytes(b"esto no es un jpeg")
        with self.assertLogs("src.core.images", level=logging.WARNING) as registro:
            self.assertIsNone(load_thumbnail(str(ruta), 360))
        self.assertIn("rota.jpg", "\n".join(registro.output))

    def test_a_missing_file_returns_none(self) -> None:
        with self.assertLogs("src.core.images", level=logging.WARNING):
            self.assertIsNone(load_thumbnail(str(Path(self.tmp.name) / "no.jpg"), 360))


class PixelLimitTests(unittest.TestCase):
    def test_the_real_deliveries_fit(self) -> None:
        """Measured on production: 12288x8192 = 100.7 Mpx per photo.

        Pillow's default ceiling is 89.5 Mpx (warning) and twice that raises.
        Those photos already sat above the warning line.
        """
        self.assertGreater(MAX_PIXELS, 12288 * 8192)
        self.assertGreater(Image.MAX_IMAGE_PIXELS, 12288 * 8192)

    def test_the_ceiling_is_finite(self) -> None:
        """map_component used to disable it outright with None."""
        self.assertIsNotNone(Image.MAX_IMAGE_PIXELS)

    def test_it_is_set_by_importing_core_not_by_luck(self) -> None:
        """It used to be a side effect of importing map_component.

        Whether the preview pane could open a 100 Mpx photo depended on
        whether an unrelated module had been imported first.
        """
        import ast
        from pathlib import Path

        raiz = Path(__file__).resolve().parent.parent / "src"
        fijan = sorted(
            str(p.relative_to(raiz))
            for p in raiz.rglob("*.py")
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
            if isinstance(n, ast.Assign)
            and any(
                isinstance(t, ast.Attribute) and t.attr == "MAX_IMAGE_PIXELS"
                for t in n.targets
            )
        )
        self.assertEqual(fijan, [str(Path("core") / "images.py")])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
