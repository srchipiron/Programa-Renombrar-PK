"""Map HTML builder.

The previous implementation embedded a huge f-string with Leaflet loaded from
a CDN.  Two changes make it nicer to operate:

1. The HTML lives in ``src/assets/map_template.html`` so editing the map
   doesn't require touching Python.
2. Leaflet + MarkerCluster ship as vendored assets under
   ``src/assets/vendor/``.  The map therefore opens offline (only the tile
   layer needs internet; OSM/CARTO fall back gracefully with a banner).
"""
from __future__ import annotations

import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Sequence

import sys

import piexif

from .core.images import load_thumbnail

logger = logging.getLogger(__name__)


def _resolve_assets_dir() -> Path:
    """Return the directory that holds ``map_template.html`` and vendors.

    When the app runs from source the assets live next to this module at
    ``src/assets``.  When frozen by PyInstaller the folder is copied into
    ``_internal/src/assets`` and ``sys._MEIPASS`` points to ``_internal``.
    """
    here_candidate = Path(__file__).resolve().parent / "assets"
    if here_candidate.is_dir():
        return here_candidate

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidate = Path(frozen_root) / "src" / "assets"
        if candidate.is_dir():
            return candidate
    return here_candidate  # Will fail later with a clear error if missing.


_ASSETS_DIR = _resolve_assets_dir()
_TEMPLATE_PATH = _ASSETS_DIR / "map_template.html"
_VENDOR = _ASSETS_DIR / "vendor"

_VENDOR_FILES = {
    "__LEAFLET_CSS__":               _VENDOR / "leaflet" / "leaflet.css",
    "__LEAFLET_JS__":                _VENDOR / "leaflet" / "leaflet.js",
    "__MARKERCLUSTER_CSS__":         _VENDOR / "markercluster" / "MarkerCluster.css",
    "__MARKERCLUSTER_DEFAULT_CSS__": _VENDOR / "markercluster" / "MarkerCluster.Default.css",
    "__MARKERCLUSTER_JS__":          _VENDOR / "markercluster" / "leaflet.markercluster.js",
}


def _asset_uri(path: Path) -> str:
    """Return a ``file://`` URL ready to drop into an ``href``/``src``."""
    return path.resolve().as_uri()


def _json_for_script(value: Any) -> str:
    """Serialise ``value`` so it is safe inside a ``<script>`` block.

    The payload carries KML placemark names and file paths, and KML files come
    from the client. A name containing ``</script>`` would close the block and
    turn the rest of the document into markup: at best the map silently fails
    to load, at worst arbitrary JS runs in the operator's browser.

    ``<``, ``>`` and ``&`` only ever occur inside JSON *strings* (the
    structural characters are ``{}[],:"`` plus numbers and literals), so
    escaping them globally is safe and leaves the decoded value identical.
    U+2028/U+2029 are valid in JSON but are line terminators in JavaScript.
    """
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


#: Head of each JPEG read to reach the embedded preview (EXIF APP1 sits at
#: the start). Measured on the production share: 28.7 ms per photo against
#: pulling a whole 10 MB file.
_EXIF_HEAD_BYTES = 128 * 1024
#: Reads are I/O bound over SMB, so they overlap well.
_THUMB_WORKERS = 8


def _embedded_thumbnail_uri(path: str) -> str:
    """``data:`` URI with the preview the camera embedded, or ``""``."""
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "rb") as handle:
            blob = piexif.load(handle.read(_EXIF_HEAD_BYTES)).get("thumbnail")
        if not blob:
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii")
    except Exception:
        return ""


def _embedded_thumbnails(paths: Sequence[str]) -> Dict[str, str]:
    """Map each path to its embedded preview, read concurrently."""
    unique = [p for p in dict.fromkeys(paths) if p]
    if not unique:
        return {}
    out: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=_THUMB_WORKERS) as pool:
        for path, uri in zip(unique, pool.map(_embedded_thumbnail_uri, unique)):
            if uri:
                out[path] = uri
    return out


class MapManager:
    """Build the interactive map HTML."""

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------
    @staticmethod
    def _get_base64_thumbnail(image_path: str, max_size: int = 300) -> str:
        img = load_thumbnail(image_path, max_size)
        if img is None:
            return ""
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=80)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{encoded}"

    # ------------------------------------------------------------------
    # HTML assembly
    # ------------------------------------------------------------------
    @staticmethod
    def build_map_html(
        points: Sequence[Dict],
        kml_coords: Sequence[Sequence[float]],
        threshold: float,
        kml_points: Sequence[Dict],
    ) -> str:
        photos_data: List[Dict] = []
        stats = {"total": len(points), "inside": 0, "outside": 0}
        # The popup used to point straight at the original: clicking a marker
        # decoded a 10-14 MB JPEG inside a Chromium that runs without the GPU.
        # The camera's own preview is ~14 KB and reaches the popup instantly;
        # the original stays behind the fullscreen click.
        thumbnails = _embedded_thumbnails([str(pt.get("path", "")) for pt in points])

        for pt in points:
            is_inside = pt["distance"] <= threshold
            if is_inside:
                stats["inside"] += 1
            else:
                stats["outside"] += 1
            path_val = pt.get("path", "")
            img_url = Path(path_val).resolve().as_uri() if path_val and os.path.exists(path_val) else ""
            photos_data.append({
                "lat": pt["lat"],
                "lon": pt["lon"],
                "name": pt["name"],
                "path": path_val,
                "img_url": img_url,
                "thumbnail": thumbnails.get(path_val, ""),
                "pk": pt.get("nearest_name") or f"PK {pt.get('pk', 0):.2f}",
                "distance": pt["distance"],
                "is_inside": is_inside,
                "gimbal_yaw": pt.get("gimbal_yaw"),
                "flight_yaw": pt.get("flight_yaw"),
                "rel_altitude": pt.get("rel_altitude"),
                "view_label": pt.get("view_label", ""),
            })


        center_lat = photos_data[0]["lat"] if photos_data else (kml_points[0]["lat"] if kml_points else 0)
        center_lon = photos_data[0]["lon"] if photos_data else (kml_points[0]["lon"] if kml_points else 0)

        replacements = {
            "__STATS_TOTAL__":    str(stats["total"]),
            "__STATS_INSIDE__":   str(stats["inside"]),
            "__STATS_OUTSIDE__":  str(stats["outside"]),
            "__THRESHOLD__":      f"{threshold:g}",
            "__CENTER_LAT__":     f"{center_lat:.6f}",
            "__CENTER_LON__":     f"{center_lon:.6f}",
            "__PHOTOS_JSON__":    _json_for_script(photos_data),
            "__KML_COORDS_JSON__": _json_for_script(list(kml_coords)),
            "__KML_POINTS_JSON__": _json_for_script(list(kml_points)),
        }
        for token, asset_path in _VENDOR_FILES.items():
            replacements[token] = _asset_uri(asset_path)

        html = _TEMPLATE_PATH.read_text(encoding="utf-8")
        for token, value in replacements.items():
            html = html.replace(token, value)
        return html

