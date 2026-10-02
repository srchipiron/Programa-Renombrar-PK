"""Parse DJI / Autel SRT telemetry into PhotoItem virtual frames."""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple

import pysrt

from .models import PhotoItem

logger = logging.getLogger(__name__)

# Format 1 / 3 / 3b: [latitude: 59.30] [longitude: 18.20]
_LAT_RE = re.compile(r"LAT(?:ITUDE)?\s*[:\]]?\s*([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
_LON_RE = re.compile(r"LON(?:GITUDE)?\s*[:\]]?\s*([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)

# Format 2 / 2b / 2c: GPS(lat,lon,alt) | GPS(lat,lon,altM) | GPS (lat, lon, alt)
_GPS_FUNC_RE = re.compile(
    r"\bGPS\s*\(\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)"
    r"(?:\s*,\s*([+-]?\d+(?:\.\d+)?)[A-Za-z]*)?\s*\)",
    re.IGNORECASE,
)

_REL_ALT_RE = re.compile(
    r"REL[_\s-]?ALT(?:ITUDE)?\s*[:\]]?\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
_ABS_ALT_RE = re.compile(
    r"ABS[_\s-]?ALT(?:ITUDE)?\s*[:\]]?\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

# Embedded wall-clock inside Format 3 bodies: 2024-01-15 14:30:22,123
_WALL_CLOCK_RE = re.compile(
    r"(\d{4}[-/:]\d{2}[-/:]\d{2})[ T](\d{2}:\d{2}:\d{2})",
)


def _digits_clock(hms: str) -> str:
    """Normalise ``HH:MM:SS`` / ``HHMMSS`` to the EXIF-style ``HHMMSS``."""
    digits = re.sub(r"\D", "", hms or "")
    return digits[:6] if len(digits) >= 6 else ""


def _digits_date(ymd: str) -> str:
    digits = re.sub(r"\D", "", ymd or "")
    return digits[:8] if len(digits) == 8 else ""


def _valid_coords(lat: float, lon: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and not (lat == 0.0 and lon == 0.0)


def extract_gps_from_srt_text(text: str) -> Optional[Tuple[float, float, Optional[float]]]:
    """Return ``(lat, lon, rel_alt_or_None)`` from one SRT cue body, or ``None``.

    Prefers the live ``GPS(...)`` tuple over bracketed latitude/longitude so
    Format 2 bodies that also mention ``HOME(lat,lon)`` do not pick the pad.
    """
    if not text:
        return None

    gps = _GPS_FUNC_RE.search(text)
    if gps:
        lat = float(gps.group(1))
        lon = float(gps.group(2))
        alt = float(gps.group(3)) if gps.group(3) is not None else None
        if _valid_coords(lat, lon):
            return lat, lon, alt

    lat_m = _LAT_RE.search(text)
    lon_m = _LON_RE.search(text)
    if lat_m and lon_m:
        lat = float(lat_m.group(1))
        lon = float(lon_m.group(1))
        if _valid_coords(lat, lon):
            alt: Optional[float] = None
            rel = _REL_ALT_RE.search(text)
            if rel:
                alt = float(rel.group(1))
            else:
                abs_m = _ABS_ALT_RE.search(text)
                if abs_m:
                    alt = float(abs_m.group(1))
            return lat, lon, alt

    return None


def extract_wall_clock(text: str) -> Tuple[str, str]:
    """Return ``(YYYYMMDD, HHMMSS)`` from an embedded wall-clock, else empty."""
    match = _WALL_CLOCK_RE.search(text or "")
    if not match:
        return "", ""
    return _digits_date(match.group(1)), _digits_clock(match.group(2))


class VideoExtractor:
    """
    Parsea subtítulos SRT de drones (DJI/Autel) que contienen latitud y longitud.
    Asocia un fotograma de texto a puntos GPS como si fuesen fotografías,
    permitiendo a RenamerLogic cruzarlos con la traza PK.
    """

    def __init__(self) -> None:
        self.srt_items: List[PhotoItem] = []

    def parse_srt(self, srt_path: str) -> List[PhotoItem]:
        self.srt_items.clear()

        try:
            subs = pysrt.open(srt_path, encoding="utf-8")
        except Exception:
            try:
                subs = pysrt.open(srt_path, encoding="iso-8859-1")
            except Exception as e:
                logger.error("Error abriendo SRT %s: %s", srt_path, e)
                return []

        for sub in subs:
            raw = sub.text or ""
            coords = extract_gps_from_srt_text(raw)
            if coords is None:
                continue
            lat, lon, alt = coords

            date_str, time_str = extract_wall_clock(raw)
            if not time_str:
                try:
                    time_str = _digits_clock(sub.start.to_time().strftime("%H:%M:%S"))
                except Exception:
                    time_str = ""

            index = len(self.srt_items)
            frame_label = time_str if time_str else f"{index:06d}"
            item = PhotoItem(
                # Cues share a wall clock second (DJI writes ~30/s), so the
                # index disambiguates both the label and the identity key.
                name=f"Frame_{frame_label}_{index:06d}.jpg",
                # No file exists per frame. A unique synthetic path keeps the
                # preview plan and the table keyed per row instead of
                # collapsing every frame onto the .srt file itself.
                path=f"{srt_path}#{index:06d}",
                lat=lat,
                lon=lon,
                date_str=date_str,
                time_str=time_str,
                rel_altitude=alt,
                virtual=True,
            )
            self.srt_items.append(item)

        if not self.srt_items:
            logger.info("SRT sin puntos GPS válidos: %s", srt_path)
        else:
            logger.info(
                "SRT %s → %d fotogramas GPS",
                srt_path,
                len(self.srt_items),
            )
        return self.srt_items
