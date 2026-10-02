"""DJI orientation helpers: XMP parse, look classification, view labels."""
from __future__ import annotations

import math
import os
import re
from typing import Any, Dict, Optional, Tuple

# Pitch near nadir ⇒ cenital. Oblique side shots usually sit around -15..-45°.
CENITAL_PITCH_MAX = -70.0  # degrees (more negative = looking down)
# Relative yaw buckets vs axis tangent (degrees).
SIDE_YAW_MIN = 45.0
SIDE_YAW_MAX = 135.0

# Sort order inside a PK burst so the slideshow "flies" consistently:
# left bank → nadir → right bank → along-track / unknown.
VIEW_SORT_RANK = {
    "TI": 0,   # talud izquierdo
    "CEN": 1,  # cenital
    "TD": 2,   # talud derecho
    "TRAZA": 3,
    "": 4,
}

_XMP_TAGS = (
    "GimbalYawDegree",
    "GimbalPitchDegree",
    "GimbalRollDegree",
    "FlightYawDegree",
    "FlightPitchDegree",
    "FlightRollDegree",
    "RelativeAltitude",
)


def _parse_float(raw: str) -> Optional[float]:
    try:
        return float(str(raw).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None


_XMP_KEY_MAP = {
    "GimbalYawDegree": "gimbal_yaw",
    "GimbalPitchDegree": "gimbal_pitch",
    "GimbalRollDegree": "gimbal_roll",
    "FlightYawDegree": "flight_yaw",
    "FlightPitchDegree": "flight_pitch",
    "FlightRollDegree": "flight_roll",
    "RelativeAltitude": "rel_altitude",
}


def parse_dji_xmp_bytes(blob: bytes | str) -> Dict[str, float]:
    """Extract DJI drone orientation tags from an XMP packet or file head."""
    if not blob:
        return {}
    text = blob.decode("latin-1", errors="ignore") if isinstance(blob, (bytes, bytearray)) else str(blob)
    out: Dict[str, float] = {}
    for tag in _XMP_TAGS:
        match = re.search(rf"(?:drone-dji:)?{tag}=\"([^\"]+)\"", text)
        if not match:
            match = re.search(rf"<[^>]*:?{tag}[^>]*>([^<]+)</", text)
        if not match:
            continue
        value = _parse_float(match.group(1))
        if value is not None:
            out[_XMP_KEY_MAP[tag]] = value
    return out


def parse_dji_xmp(path: str, *, max_bytes: int = 1_000_000) -> Dict[str, float]:
    """Extract DJI drone orientation tags from embedded XMP on disk.

    Prefer :func:`parse_dji_xmp_bytes` with bytes already in memory (e.g. Pillow
    ``Image.info['xmp']``) to avoid a second open/read of the JPEG — critical
    on network shares during cold analysis.
    """
    try:
        with open(path, "rb") as fh:
            blob = fh.read(max_bytes)
    except OSError:
        return {}
    return parse_dji_xmp_bytes(blob)


def normalize_angle_deg(angle: float) -> float:
    """Wrap angle to (-180, 180]."""
    wrapped = (angle + 180.0) % 360.0 - 180.0
    return 180.0 if wrapped == -180.0 else wrapped


def relative_yaw_to_axis(gimbal_yaw: float, axis_bearing: float) -> float:
    """Camera look relative to axis tangent (0 = along axis, ±90 = perpendicular)."""
    return normalize_angle_deg(gimbal_yaw - axis_bearing)


def classify_view(
    *,
    gimbal_yaw: Optional[float],
    gimbal_pitch: Optional[float],
    axis_bearing: Optional[float],
) -> str:
    """Return ``CEN`` / ``TD`` / ``TI`` / ``TRAZA`` / ``""``.

    TD/TI use the sign of relative yaw vs the axis (right-hand rule in map
    frame: positive relative yaw ⇒ talud derecho).
    """
    if gimbal_pitch is not None and gimbal_pitch <= CENITAL_PITCH_MAX:
        return "CEN"
    if gimbal_yaw is None or axis_bearing is None:
        return ""
    rel = relative_yaw_to_axis(gimbal_yaw, axis_bearing)
    abs_rel = abs(rel)
    if SIDE_YAW_MIN <= abs_rel <= SIDE_YAW_MAX:
        return "TD" if rel > 0 else "TI"
    return "TRAZA"


def view_sort_rank(view_label: Optional[str]) -> int:
    return VIEW_SORT_RANK.get((view_label or "").upper(), 4)


def orientation_payload(
    path: Optional[str] = None,
    *,
    xmp: Optional[bytes | str] = None,
) -> Dict[str, Any]:
    """Convenience dict suitable for merging into EXIF cache payloads.

    Pass ``xmp`` (Pillow ``info['xmp']`` or raw APP1 body) to avoid reopening
    the JPEG.  ``path`` remains as a fallback for callers that only have a
    filesystem path.
    """
    if xmp is not None:
        meta = parse_dji_xmp_bytes(xmp)
    elif path:
        meta = parse_dji_xmp(path)
    else:
        meta = {}
    return {
        "gimbal_yaw": meta.get("gimbal_yaw"),
        "gimbal_pitch": meta.get("gimbal_pitch"),
        "gimbal_roll": meta.get("gimbal_roll"),
        "flight_yaw": meta.get("flight_yaw"),
        "rel_altitude": meta.get("rel_altitude"),
    }


def xmp_blob_from_pil(img: Any) -> Optional[bytes | str]:
    """Return XMP bytes already parsed by Pillow, or a drone-dji APP1 from applist.

    Pillow's JPEG parser walks APP markers once on open and stores Adobe XMP in
    ``info['xmp']``.  Using that avoids a second ``open`` + 1 MiB read/decode
    per photo during analysis.
    """
    xmp = getattr(img, "info", {}).get("xmp")
    if xmp:
        return xmp
    for entry in getattr(img, "applist", ()) or ():
        if not entry or len(entry) < 2:
            continue
        segment, content = entry[0], entry[1]
        if segment != "APP1" or not isinstance(content, (bytes, bytearray)):
            continue
        if b"drone-dji" in content or b"GimbalYawDegree" in content:
            return bytes(content)
    return None


def extract_jpeg_xmp_packet(path: str) -> Optional[bytes]:
    """Return the raw APP1 XMP segment payload (including marker), if present."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker in (0xD8, 0xD9):  # SOI / EOI
            i += 2
            continue
        if marker == 0xDA:  # SOS — image data follows
            break
        if i + 4 > len(data):
            break
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        segment_end = i + 2 + length
        if segment_end > len(data):
            break
        if marker == 0xE1:  # APP1
            payload = data[i + 4 : segment_end]
            if payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00") or b"drone-dji" in payload:
                return data[i:segment_end]
        i = segment_end
    return None


def inject_jpeg_xmp_packet(path: str, xmp_segment: bytes) -> bool:
    """Insert/replace an APP1 XMP segment after SOI (and after existing EXIF APP1)."""
    try:
        with open(path, "rb") as fh:
            data = bytearray(fh.read())
    except OSError:
        return False
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return False

    # Strip existing XMP APP1 segments so we don't duplicate.
    i = 2
    pieces = [data[0:2]]
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            pieces.append(data[i:])
            break
        marker = data[i + 1]
        if marker == 0xDA:
            pieces.append(data[i:])
            break
        if marker in (0xD8, 0xD9):
            pieces.append(data[i : i + 2])
            i += 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        segment_end = i + 2 + length
        if segment_end > len(data):
            pieces.append(data[i:])
            break
        payload = data[i + 4 : segment_end]
        is_xmp = marker == 0xE1 and (
            payload.startswith(b"http://ns.adobe.com/xap/1.0/\x00") or b"drone-dji" in payload
        )
        if not is_xmp:
            pieces.append(data[i:segment_end])
        i = segment_end

    rebuilt = bytearray(pieces[0])
    # Place XMP after SOI / first EXIF APP1 if present.
    insert_at = 2
    rest = bytearray()
    for chunk in pieces[1:]:
        rest.extend(chunk)
    if len(rest) >= 4 and rest[0] == 0xFF and rest[1] == 0xE1:
        # Keep first APP1 (usually EXIF), then XMP, then the remainder.
        exif_len = int.from_bytes(rest[2:4], "big")
        exif_end = 2 + exif_len
        rebuilt.extend(rest[:exif_end])
        rebuilt.extend(xmp_segment)
        rebuilt.extend(rest[exif_end:])
    else:
        rebuilt.extend(xmp_segment)
        rebuilt.extend(rest)

    # Atomic replace: never truncate the live JPEG before the new bytes are
    # fully written. A mid-write crash with open(..., "wb") would wipe the file.
    tmp_path = f"{path}.__xmp_tmp__"
    try:
        with open(tmp_path, "wb") as fh:
            fh.write(rebuilt)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except OSError:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return False
    return True
