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
import logging
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import sys

from PIL import ExifTags, Image

Image.MAX_IMAGE_PIXELS = None  # Prevent DecompressionBombError for high-res drone images

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


class MapManager:
    """Build the interactive map HTML."""

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------
    @staticmethod
    def _get_base64_thumbnail(image_path: str, max_size: int = 300) -> str:
        try:
            with Image.open(image_path) as img:
                img.draft("RGB", (max_size, max_size))
                try:
                    orientation_key = None
                    for k, v in ExifTags.TAGS.items():
                        if v == "Orientation":
                            orientation_key = k
                            break
                    # Use the public getexif() API (available since Pillow 6.0).
                    # _getexif() is a private JPEG-only method that doesn't exist
                    # on PNG/TIFF and was removed from the public surface in newer
                    # Pillow releases.
                    exif = img.getexif() if hasattr(img, "getexif") else None
                    if exif and orientation_key is not None and orientation_key in exif:
                        orient = exif[orientation_key]
                        if orient == 3:
                            img = img.rotate(180, expand=True)
                        elif orient == 6:
                            img = img.rotate(270, expand=True)
                        elif orient == 8:
                            img = img.rotate(90, expand=True)
                except Exception:
                    pass
                img.thumbnail((max_size, max_size))
                buffer = io.BytesIO()
                img.convert("RGB").save(buffer, format="JPEG", quality=80)
                encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
                return f"data:image/jpeg;base64,{encoded}"
        except Exception as exc:
            logger.debug("Thumbnail failed for %s: %s", image_path, exc)
            return ""

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
            "__PHOTOS_JSON__":    json.dumps(photos_data),
            "__KML_COORDS_JSON__": json.dumps(list(kml_coords)),
            "__KML_POINTS_JSON__": json.dumps(list(kml_points)),
        }
        for token, asset_path in _VENDOR_FILES.items():
            replacements[token] = _asset_uri(asset_path)

        html = _TEMPLATE_PATH.read_text(encoding="utf-8")
        for token, value in replacements.items():
            html = html.replace(token, value)
        return html

    @staticmethod
    def generate_and_open_map(
        points: list,
        kml_coords: list,
        threshold: float,
        output_folder: Optional[str],
        kml_points: list,
    ) -> str:
        """Build the HTML, write it to a temp file and open it in the browser."""
        html_content = MapManager.build_map_html(points, kml_coords, threshold, kml_points)
        fd, path = tempfile.mkstemp(suffix=".html", prefix="visor_pks_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(html_content)
        webbrowser.open(Path(path).as_uri())
        return path
