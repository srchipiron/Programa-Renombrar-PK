"""Reading photo thumbnails: one implementation, no Qt.

The preview pane and the map each had their own copy of open + draft +
EXIF orientation + resize. They drifted: the map was fixed to use Pillow's
public ``getexif()`` while the preview kept the private, JPEG-only
``_getexif()``, so PNG and TIFF previews were never rotated. Rather than fix
the same thing twice again, both now call in here.

Qt-free on purpose: this runs in worker threads and belongs in ``core``.
"""
from __future__ import annotations

import logging
from typing import Optional

from PIL import ExifTags, Image

logger = logging.getLogger(__name__)

#: Pillow refuses images above twice ``MAX_IMAGE_PIXELS``, a guard against
#: decompression bombs. Its default of 89.5 Mpx is below what this program is
#: for: the deliveries measured 12288x8192 = 100.7 Mpx, which already trips the
#: warning and leaves only x1.78 of headroom before Pillow *raises* and the
#: thumbnail silently comes back blank. These files come from the company's own
#: drone over its own share, so the limit is raised deliberately -- but kept
#: finite, at roughly four times the largest panorama seen. It is set once, on
#: import, rather than saved and restored around each read: both callers decode
#: from several threads at a time, so a per-call swap would race.
MAX_PIXELS = 400_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

#: EXIF tag id for Orientation, resolved once instead of scanning ExifTags.TAGS
#: on every photo.
_ORIENTATION_TAG: Optional[int] = next(
    (k for k, v in ExifTags.TAGS.items() if v == "Orientation"), None
)

#: EXIF orientation value -> counter-clockwise rotation that undoes it.
_ROTATIONS = {3: 180, 6: 270, 8: 90}


def _apply_orientation(img: Image.Image) -> Image.Image:
    """Rotate to how the camera was actually held, if it recorded that."""
    if _ORIENTATION_TAG is None:
        return img
    try:
        # Public API since Pillow 6.0. The private _getexif() is JPEG-only.
        exif = img.getexif() if hasattr(img, "getexif") else None
        if not exif:
            return img
        angle = _ROTATIONS.get(exif.get(_ORIENTATION_TAG))
        return img.rotate(angle, expand=True) if angle else img
    except Exception as exc:  # una orientacion ilegible no impide la miniatura
        logger.debug("Orientacion EXIF ilegible: %s", exc)
        return img


def load_thumbnail(path: str, max_size: int) -> Optional[Image.Image]:
    """Return an RGB thumbnail no larger than ``max_size``, or None.

    Returns None rather than raising: a photo that will not open must not take
    down the pane that is listing two thousand of them. The reason is logged,
    so a blank preview leaves a trace in the log and the diagnostic report.
    """
    try:
        with Image.open(path) as img:
            # draft() lets the JPEG decoder work at 1/2, 1/4 or 1/8 scale: on a
            # 100 Mpx panorama that is the difference between a thumbnail and a
            # full decode.
            img.draft("RGB", (max_size, max_size))
            img = _apply_orientation(img)
            img.thumbnail((max_size, max_size))
            # copy() so the result outlives the closing of the file.
            return img.convert("RGB").copy()
    except Exception as exc:
        logger.warning("No se pudo leer la miniatura de %s: %s", path, exc)
        return None
