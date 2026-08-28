"""Preview thumbnails: cached, and something on screen straight away.

Browsing a delivery meant re-decoding a 14 MB JPEG on every selection —
measured at 107–123 ms each, with the pane blank meanwhile, and paid again
every time the operator went back to a photo.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import piexif
import pytest
from PIL import Image

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtGui import QPixmap  # noqa: E402

from src.ui_qt.preview_tab import (  # noqa: E402
    _EXIF_HEAD_BYTES,
    _ThumbnailCache,
    _read_embedded_thumbnail,
    _read_thumbnail,
)


def _photo_with_thumbnail(path: Path, size=(1200, 900), thumb=(256, 144)) -> None:
    """A JPEG carrying an embedded preview, like the camera writes."""
    buf = io.BytesIO()
    Image.new("RGB", thumb, (10, 120, 30)).save(buf, "JPEG")
    exif = piexif.dump({"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": buf.getvalue()})
    Image.new("RGB", size, (30, 60, 90)).save(path, "JPEG", exif=exif, quality=80)


class EmbeddedThumbnailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.photo = Path(self.tmp.name) / "DJI_0001.jpg"
        _photo_with_thumbnail(self.photo)

    def test_returns_the_camera_preview(self) -> None:
        pixmap = _read_embedded_thumbnail(str(self.photo), 360)
        self.assertIsInstance(pixmap, QPixmap)
        self.assertFalse(pixmap.isNull())
        # It is the small preview, not the full render.
        self.assertLessEqual(pixmap.width(), 256)

    def test_only_the_head_of_the_file_is_needed(self) -> None:
        """The point is not reading 14 MB over SMB to show a placeholder."""
        with open(self.photo, "rb") as handle:
            head = handle.read(_EXIF_HEAD_BYTES)
        self.assertIsNotNone(piexif.load(head).get("thumbnail"))

    def test_a_photo_without_a_preview_is_not_an_error(self) -> None:
        plain = Path(self.tmp.name) / "sin_thumb.jpg"
        Image.new("RGB", (400, 300)).save(plain, "JPEG")
        self.assertIsNone(_read_embedded_thumbnail(str(plain), 360))

    def test_a_missing_file_is_not_an_error(self) -> None:
        self.assertIsNone(_read_embedded_thumbnail(str(Path(self.tmp.name) / "no.jpg"), 360))

    def test_the_full_render_is_bigger_than_the_placeholder(self) -> None:
        rapida = _read_embedded_thumbnail(str(self.photo), 360)
        completa = _read_thumbnail(str(self.photo), 360)
        self.assertIsNotNone(completa)
        self.assertGreater(completa.width(), rapida.width())


class ThumbnailCacheTests(unittest.TestCase):
    def test_returns_what_was_stored(self) -> None:
        cache = _ThumbnailCache(capacity=4)
        pixmap = QPixmap(8, 8)
        cache.put(("a.jpg", 360), pixmap)
        self.assertIs(cache.get(("a.jpg", 360)), pixmap)
        self.assertIsNone(cache.get(("b.jpg", 360)))

    def test_size_is_part_of_the_key(self) -> None:
        cache = _ThumbnailCache()
        cache.put(("a.jpg", 360), QPixmap(8, 8))
        self.assertIsNone(cache.get(("a.jpg", 720)))

    def test_evicts_the_least_recently_used(self) -> None:
        cache = _ThumbnailCache(capacity=2)
        for name in ("a", "b"):
            cache.put((name, 360), QPixmap(4, 4))
        cache.get(("a", 360))          # 'a' vuelve a ser el reciente
        cache.put(("c", 360), QPixmap(4, 4))

        self.assertIsNone(cache.get(("b", 360)))
        self.assertIsNotNone(cache.get(("a", 360)))
        self.assertIsNotNone(cache.get(("c", 360)))

    def test_failed_reads_are_not_cached(self) -> None:
        """A None must not poison the entry and hide a later successful read."""
        cache = _ThumbnailCache()
        cache.put(("a.jpg", 360), None)
        self.assertIsNone(cache.get(("a.jpg", 360)))
        cache.put(("a.jpg", 360), QPixmap(4, 4))
        self.assertIsNotNone(cache.get(("a.jpg", 360)))

    def test_clear(self) -> None:
        cache = _ThumbnailCache()
        cache.put(("a.jpg", 360), QPixmap(4, 4))
        cache.clear()
        self.assertIsNone(cache.get(("a.jpg", 360)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
