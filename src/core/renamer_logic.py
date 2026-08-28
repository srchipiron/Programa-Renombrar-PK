import math
import os
import re
import csv
import json
import shutil
import logging
import statistics
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
import piexif
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from .rename_report import (
    RENAME_REPORT_FILENAME,
    load_rename_operations,
    relative_mapping_key,
    report_csv_path,
    save_rename_report,
    undo_rename_operations,
)
from .spatial_calculator import SpatialCalculator, METERS_PER_DEGREE
from .models import PhotoItem
from .types import RenameStats
from .orientation import (
    classify_view,
    extract_jpeg_xmp_packet,
    inject_jpeg_xmp_packet,
    orientation_payload,
    view_sort_rank,
    xmp_blob_from_pil,
)

try:
    from piexif import helper as piexif_helper
except Exception:
    piexif_helper = None

DEFAULT_MAX_WORKERS = 4
DEFAULT_TUKEY_MULTIPLIER = 1.5

# Auto-threshold bounds (meters). Below 10m GNSS noise dominates; above 250m
# we risk wrapping takeoff/approach passes into the "inside" bucket.
AUTO_THRESHOLD_MIN = 10.0
AUTO_THRESHOLD_MAX = 250.0
AUTO_THRESHOLD_DEFAULT = 30.0

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".tif", ".tiff")

# Sidecar extensions that travel alongside a photo (same basename) and must be
# renamed together.  Lowercase, including leading dot.
SIDECAR_EXTENSIONS = {
    ".dng", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".rw2", ".orf", ".raf",
    ".pef", ".srw", ".3fr", ".iiq", ".x3f",
    ".xmp", ".thm", ".wav",
}

#: Cache file written inside each analyzed folder so repeated analyses skip
#: EXIF I/O on files that haven't changed.
CACHE_FILENAME = ".pk_exif_cache.json"
CACHE_VERSION = 3

#: Directory names created by the renamer itself.  Re-analysis must not walk
#: into them or backups / already-routed deliveries get double-counted and
#: risk being renamed again.
ANALYSIS_SKIP_DIR_NAMES = frozenset({
    "_backup_originales",
    "viaductos",
    "vertederos",
    "otros",
})

logger = logging.getLogger(__name__)


def is_analysis_skip_dir(name: str) -> bool:
    """True when ``name`` is a renamer-managed folder that analysis must ignore."""
    return bool(name) and name.casefold() in ANALYSIS_SKIP_DIR_NAMES


class SidecarIndex:
    """Sidecar lookup backed by **one** directory listing instead of one per photo.

    Looking companions up one photo at a time means re-listing the directory
    per photo, i.e. O(files²) per folder: 7 s for 2000 photos on a local SSD,
    and far worse on the SMB shares where production jobs actually live.
    Analysis asks about every photo of the same directory, so the listing is
    done once and every later lookup is served from memory.

    The index is populated eagerly by :func:`collect_analysis_tree` (free — it
    reuses the ``os.walk`` that already enumerates the tree), and falls back to
    scanning on demand for a directory it has not seen. Analysis only looks up
    paths produced by that same walk, so every directory is already registered
    and the worker pool performs read-only lookups — no locking needed.
    """

    __slots__ = ("_dirs",)

    def __init__(self) -> None:
        # normcased dir -> {file stem: [sidecar paths]}
        self._dirs: Dict[str, Dict[str, List[str]]] = {}

    @staticmethod
    def _dir_key(directory: str) -> str:
        return os.path.normcase(os.path.abspath(directory or "."))

    def add_directory(self, directory: str, names: Iterable[str]) -> None:
        """Register the file *names* contained in ``directory`` (no I/O)."""
        stems: Dict[str, List[str]] = {}
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext.lower() in SIDECAR_EXTENSIONS:
                stems.setdefault(stem, []).append(os.path.join(directory, name))
        self._dirs[self._dir_key(directory)] = stems

    def _entries(self, directory: str) -> Dict[str, List[str]]:
        key = self._dir_key(directory)
        cached = self._dirs.get(key)
        if cached is None:
            cached = _scan_sidecar_stems(directory)
            self._dirs[key] = cached
        return cached

    def find(self, photo_path: str) -> List[str]:
        """Return sidecar files sharing ``photo_path``'s basename stem."""
        directory = os.path.dirname(photo_path)
        stem = os.path.splitext(os.path.basename(photo_path))[0]
        return [p for p in self._entries(directory).get(stem, ()) if p != photo_path]

    def forget(self, directory: str) -> None:
        """Drop a cached listing (call after the directory changes on disk)."""
        self._dirs.pop(self._dir_key(directory), None)


def _scan_sidecar_stems(directory: str) -> Dict[str, List[str]]:
    """One ``os.scandir`` pass returning ``{stem: [sidecar paths]}``."""
    stems: Dict[str, List[str]] = {}
    try:
        with os.scandir(directory or ".") as it:
            for entry in it:
                if not entry.is_file():
                    continue
                stem, ext = os.path.splitext(entry.name)
                if ext.lower() in SIDECAR_EXTENSIONS:
                    stems.setdefault(stem, []).append(entry.path)
    except OSError:
        return {}
    return stems


def collect_analysis_tree(folder: str) -> Tuple[List[str], SidecarIndex]:
    """Walk ``folder`` once, returning image paths **and** a sidecar index.

    Building the sidecar index here is free: ``os.walk`` already hands us every
    filename in every directory, so companions are indexed without a second
    round of directory listings (the dominant cost on network shares).
    """
    image_files: List[str] = []
    index = SidecarIndex()
    if not folder or not os.path.isdir(folder):
        return image_files, index
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not is_analysis_skip_dir(d)]
        index.add_directory(root, files)
        for name in files:
            if name.lower().endswith(IMAGE_EXTENSIONS):
                image_files.append(os.path.join(root, name))
    return image_files, index


def collect_analysis_image_files(folder: str) -> List[str]:
    """Recursively list image files under ``folder``, pruning work/backup dirs.

    ``os.walk`` mutates ``dirs`` in place so pruned directories are never entered.
    Matching is case-insensitive (Windows delivery trees vary in casing).
    """
    return collect_analysis_tree(folder)[0]


def safe_join_under(base_folder: str, *parts: str) -> Optional[str]:
    """Join ``parts`` under ``base_folder`` only when the result stays inside.

    Rejects empty segments, absolute paths, drive letters and ``..`` escapes so
    landmark ``folder`` values from config cannot write outside the job tree.
    """
    if not base_folder or not parts:
        return None
    cleaned: List[str] = []
    for part in parts:
        text = str(part or "").strip().replace("\\", "/")
        if not text:
            return None
        for segment in text.split("/"):
            segment = segment.strip()
            if not segment or segment in (".", ".."):
                return None
            if os.path.isabs(segment) or (len(segment) >= 2 and segment[1] == ":"):
                return None
            cleaned.append(segment)
    if not cleaned:
        return None
    base_abs = os.path.abspath(base_folder)
    candidate = os.path.abspath(os.path.join(base_abs, *cleaned))
    try:
        if os.path.commonpath([base_abs, candidate]) != base_abs:
            return None
    except ValueError:
        return None
    return candidate


def _percentile(sorted_values: List[float], fraction: float) -> float:
    """Return an interpolated percentile from a pre-sorted list.

    We use linear interpolation between the two nearest ranks so that small
    samples don't get pushed to the extremes by the ``int(n*p)`` truncation
    used historically.
    """
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])
    fraction = max(0.0, min(1.0, fraction))
    pos = fraction * (n - 1)
    low = int(pos)
    high = min(low + 1, n - 1)
    weight = pos - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def compute_suggested_threshold(
    distances: List[float],
    *,
    tukey_multiplier: float = DEFAULT_TUKEY_MULTIPLIER,
) -> Dict[str, Any]:
    """Return a robust threshold proposal plus the stats that justify it.

    The algorithm is layered:
        - ``empty``          : nothing to work with, return the default.
        - ``single_sample``  : one measurement, clamp to a sane minimum.
        - ``small_sample``   : n<4, use the max with a small safety margin.
        - ``degenerate``     : all values equal, use that value clamped.
        - ``iqr_strict``     : Q3 + 1.5*IQR when it covers >=90% of samples.
        - ``iqr_relaxed``    : average of IQR upper bound and P90 when the
                               strict bound would discard too many samples.

    The final value is always clamped to the
    ``[AUTO_THRESHOLD_MIN, AUTO_THRESHOLD_MAX]`` window to stay within sane
    topographic tolerances.  The returned dict also exposes the full set of
    descriptive statistics so the UI can explain *why* a value was chosen.
    """
    cleaned = [float(d) for d in distances if d is not None and d != float("inf")]
    samples = len(cleaned)

    if samples == 0:
        return {
            "suggested": AUTO_THRESHOLD_DEFAULT,
            "method": "empty",
            "samples": 0,
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "stdev": 0.0,
            "q1": 0.0,
            "q3": 0.0,
            "iqr": 0.0,
            "p90": 0.0,
        }

    sorted_d = sorted(cleaned)
    min_d = sorted_d[0]
    max_d = sorted_d[-1]
    mean_d = sum(sorted_d) / samples
    median_d = _percentile(sorted_d, 0.5)
    q1 = _percentile(sorted_d, 0.25)
    q3 = _percentile(sorted_d, 0.75)
    iqr = q3 - q1
    p90 = _percentile(sorted_d, 0.90)
    try:
        stdev_d = statistics.stdev(sorted_d) if samples > 1 else 0.0
    except statistics.StatisticsError:
        stdev_d = 0.0

    if samples == 1:
        suggested = max(AUTO_THRESHOLD_MIN, min(sorted_d[0] * 1.25, AUTO_THRESHOLD_MAX))
        method = "single_sample"
    elif max_d - min_d < 1e-6:
        # All samples equal: just use that value clamped to a sane range.
        suggested = max(AUTO_THRESHOLD_MIN, min(max_d, AUTO_THRESHOLD_MAX))
        method = "degenerate"
    elif samples < 4:
        suggested = max_d * 1.05 if max_d > 0 else AUTO_THRESHOLD_DEFAULT
        method = "small_sample"
    else:
        upper_bound = q3 + (tukey_multiplier * iqr)
        # If P90 itself lies beyond what we consider a sane topographic range
        # (``AUTO_THRESHOLD_MAX``) it means the tail is dominated by garbage
        # outliers (corrupt EXIF, unrelated photos, ...).  Trusting it would
        # pull the "relaxed" midpoint into the sky, so we fall back to the
        # strict bound, which is computed from robust quartiles.
        if p90 > AUTO_THRESHOLD_MAX:
            suggested = upper_bound
            method = "iqr_strict"
        elif upper_bound < p90:
            # The strict IQR bound would discard more than ~10% of samples, so
            # relax it towards P90 to avoid being overly aggressive.
            suggested = (upper_bound + p90) / 2.0
            method = "iqr_relaxed"
        else:
            suggested = upper_bound
            method = "iqr_strict"

    suggested = max(AUTO_THRESHOLD_MIN, min(float(suggested), AUTO_THRESHOLD_MAX))

    return {
        "suggested": suggested,
        "method": method,
        "samples": samples,
        "min": min_d,
        "max": max_d,
        "mean": mean_d,
        "median": median_d,
        "stdev": stdev_d,
        "q1": q1,
        "q3": q3,
        "iqr": iqr,
        "p90": p90,
    }

def histogram_axis_upper(
    distances: List[float],
    threshold: float,
    *,
    tukey_multiplier: float = DEFAULT_TUKEY_MULTIPLIER,
    floor_m: float = 10.0,
) -> float:
    """Upper bound of the distance axis so the decision zone stays legible.

    A real delivery mixes a tight corridor cluster with a handful of photos
    kilometres away (take-off, a different site). Scaling the axis to the
    maximum then puts every corridor photo in the first bin: measured on a
    238-photo job whose distances span 0–1495 m with 215 of them under 20 m,
    the whole histogram collapsed into a single bar.

    The bound follows the decision instead — the threshold and the robust
    spread of the sample — and whatever lies beyond is meant to be counted in
    an overflow bin, never dropped. Never exceeds the largest distance, so the
    plot has no empty tail.
    """
    cleaned = [float(d) for d in distances if d is not None and d != float("inf")]
    if not cleaned:
        return max(floor_m, float(threshold) * 1.5)

    max_d = max(cleaned)
    candidates = [float(threshold) * 1.5, floor_m]
    if len(cleaned) >= 4:
        ordered = sorted(cleaned)
        q1 = _percentile(ordered, 0.25)
        q3 = _percentile(ordered, 0.75)
        candidates.append(q3 + tukey_multiplier * (q3 - q1))
    else:
        candidates.append(max_d)

    upper = max(candidates)
    return min(upper, max_d) if max_d > 0 else max(floor_m, upper)


def _convert_dms_to_dd(dms, ref) -> float:
    """Convert an EXIF DMS triplet into a signed decimal degree."""
    if len(dms) < 3:
        raise ValueError("Invalid DMS data length")
    if dms[0][1] == 0 or dms[1][1] == 0 or dms[2][1] == 0:
        raise ValueError("Invalid DMS denominator")
    degrees = dms[0][0] / dms[0][1]
    minutes = dms[1][0] / dms[1][1]
    seconds = dms[2][0] / dms[2][1]
    dd = degrees + minutes / 60 + seconds / 3600
    if ref in (b"S", b"W", "S", "W"):
        dd = -dd
    return dd


def _parse_exif_datetime(dt_val: str) -> Tuple[str, str]:
    """Parse an EXIF ``DateTimeOriginal`` string into ``(YYYYMMDD, HHMMSS)``.

    Handles a few tolerant variants emitted by cameras in the wild:

    - Canonical ``2026:04:21 14:23:45``.
    - With sub-second (``2026:04:21 14:23:45.123``) or ``,`` separator.
    - ISO 8601 ``2026-04-21T14:23:45``.
    - Timezone suffix ``2026:04:21 14:23:45+02:00`` (DJI Fly).
    """
    if not dt_val:
        return "", ""
    s = dt_val.strip().replace("T", " ")
    # Drop sub-second fraction.
    s = re.split(r"[.,]", s, maxsplit=1)[0]
    # Drop trailing timezone suffix (``+02:00`` / ``Z``).
    s = re.split(r"[+Z]", s, maxsplit=1)[0].strip()
    if " " not in s or len(s) < 15:
        return "", ""
    d_part, t_part = s.split(" ", 1)
    d_digits = re.sub(r"\D", "", d_part)
    t_digits = re.sub(r"\D", "", t_part)
    if len(d_digits) != 8 or len(t_digits) < 6:
        return "", ""
    return d_digits, t_digits[:6]


def find_sidecars(photo_path: str) -> List[str]:
    """Return a list of sidecar files that share the same basename.

    Single-shot helper kept for callers that only look at one photo. Batch
    callers must use :class:`SidecarIndex` so the directory is listed once
    instead of once per photo.
    """
    return SidecarIndex().find(photo_path)


def _safe_unlink(path: str) -> None:
    """Best-effort remove of a temp sibling; never raises to callers."""
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _try_rename(src: str, dst: str) -> bool:
    """Rename ``src`` → ``dst`` when safe; return False on collision/OS error."""
    try:
        if not src or not dst or src == dst:
            return True
        if not os.path.exists(src):
            return False
        if os.path.exists(dst):
            return False
        os.rename(src, dst)
        return True
    except OSError as exc:
        logger.warning("Rename falló %s → %s: %s", src, dst, exc)
        return False


def _unique_backup_path(dest: str) -> str:
    """Return ``dest`` or ``stem__N.ext`` when ``dest`` already exists."""
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(dest)
    n = 1
    while True:
        candidate = f"{stem}__{n}{ext}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _copy_backup_original(src_path: str, base_folder: str, backup_folder: str) -> str:
    """Copy ``src_path`` under ``backup_folder``, mirroring its source relative dir.

    Using the *source* tree (not the rename destination) prevents two inputs
    that share a basename and collapse into the same output folder from
    silently overwriting each other in the backup.
    """
    parent = os.path.dirname(src_path)
    try:
        rel_parent = os.path.relpath(parent, base_folder)
    except ValueError:
        rel_parent = "."
    if rel_parent in (".", ""):
        bck_dir = backup_folder
    else:
        bck_dir = os.path.join(backup_folder, rel_parent)
    os.makedirs(bck_dir, exist_ok=True)
    dest = _unique_backup_path(os.path.join(bck_dir, os.path.basename(src_path)))
    shutil.copy2(src_path, dest)
    return dest


# ---------------------------------------------------------------------------
# Work-type ordering (vertedero / viaducto / otros) from folder names
# ---------------------------------------------------------------------------
# Rank 0 sorts first. Any path segment (case-insensitive) containing one of
# the keywords contributes; the smallest rank among all segments wins so
# ``…/Viaductos/…/puente_aux/…`` still counts as viaducto/puente.
_WORK_TYPE_GROUPS: Tuple[Tuple[str, ...], ...] = (
    (
        "vertedero",
        "vertederos",
        "basurero",
        "basureros",
        "relleno",
        "rsu",
        "celda",
    ),
    (
        "viaducto",
        "viaductos",
        "puente",
        "puentes",
        "estribo",
        "estribos",
        "tablero",
        "pila",
        "pilas",
    ),
)
_OTHERS_RANK = len(_WORK_TYPE_GROUPS)


def path_work_type_rank(path: str) -> int:
    """Return 0 vertedero…, 1 viaducto/puente…, or ``_OTHERS_RANK`` (otros)."""
    try:
        parts = [p.casefold() for p in Path(os.path.normpath(path)).expanduser().parent.parts]
    except (OSError, ValueError):
        return _OTHERS_RANK

    best = _OTHERS_RANK
    for part in parts:
        for rank, keywords in enumerate(_WORK_TYPE_GROUPS):
            if any(k in part for k in keywords):
                best = min(best, rank)
    return best


def path_work_type_sort_prefix(path: str) -> Tuple[int, str]:
    """(obra_rank, parent_path) for stable ordering within the same obra."""
    rank = path_work_type_rank(path)
    try:
        rel = Path(os.path.normpath(path)).expanduser().parent.as_posix().casefold()
    except (OSError, ValueError):
        rel = path.casefold()
    return (rank, rel)


def photo_work_type_sort_key(item: PhotoItem) -> Tuple[Any, ...]:
    """Orden: tipo de obra → PK → vista (TI/CEN/TD/TRAZA) → fecha/hora → nombre."""
    rank, rel = path_work_type_sort_prefix(item.path)
    return (
        rank,
        rel,
        float(item.pk_value or 0.0),
        view_sort_rank(item.view_label),
        item.date_str or "",
        item.time_str or "",
        item.name.casefold(),
    )


def _walked_image_path_sort_key(full_path: str) -> Tuple[Any, ...]:
    """Orden al listar recursivamente (aún sin EXIF)."""
    rank, rel = path_work_type_sort_prefix(full_path)
    return (rank, rel, os.path.basename(full_path).casefold())


def mark_duplicates(
    items: List[PhotoItem],
    *,
    gps_tolerance_m: float = 1.0,
    time_tolerance_s: int = 2,
) -> int:
    """Mark as duplicates photos sharing near-identical GPS and timestamp.

    Returns the number of items flagged as duplicate.  The first
    encountered photo in each cluster is kept as "original" and the rest
    point back to it via :attr:`PhotoItem.duplicate_of`.

    Candidates are bucketed on a ``gps_tolerance_m``-sized grid keyed by
    date, so each photo only needs to check the ~9 neighbouring cells
    instead of every previously-kept photo. This keeps large batches
    (thousands of photos) at roughly O(n) instead of the O(n * kept) scan a
    naive nested loop would do.
    """
    if not items:
        return 0
    # Reset any previous flag before recomputing.
    for it in items:
        it.duplicate_of = None

    ordered = sorted(items, key=photo_work_type_sort_key)
    lat_tol = gps_tolerance_m / METERS_PER_DEGREE
    lat_cell = max(lat_tol, 1e-9)
    buckets: Dict[Tuple[str, int, int], List[PhotoItem]] = {}
    flagged = 0

    for candidate in ordered:
        # Longitude degrees shrink with latitude; ignore this and Spain (~37–40°N)
        # gets a ~20–25% wrong east-west tolerance (missed or false duplicates).
        cos_lat = max(abs(math.cos(math.radians(candidate.lat))), 0.01)
        lon_tol = gps_tolerance_m / (METERS_PER_DEGREE * cos_lat)
        lon_cell = max(lon_tol, 1e-9)
        cx = int(candidate.lat // lat_cell)
        cy = int(candidate.lon // lon_cell)
        match: Optional[PhotoItem] = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for ref in buckets.get((candidate.date_str, cx + dx, cy + dy), ()):
                    if abs(candidate.lat - ref.lat) > lat_tol:
                        continue
                    # Recompute lon tolerance at the midpoint so polar stretch
                    # does not favour whichever photo was seen first.
                    mid_lat = (candidate.lat + ref.lat) / 2.0
                    mid_cos = max(abs(math.cos(math.radians(mid_lat))), 0.01)
                    pair_lon_tol = gps_tolerance_m / (METERS_PER_DEGREE * mid_cos)
                    if abs(candidate.lon - ref.lon) > pair_lon_tol:
                        continue
                    if _timestamp_delta_seconds(candidate, ref) > time_tolerance_s:
                        continue
                    match = ref
                    break
                if match:
                    break
            if match:
                break

        if match is not None:
            candidate.duplicate_of = match.name
            flagged += 1
        else:
            buckets.setdefault((candidate.date_str, cx, cy), []).append(candidate)

    return flagged


def _timestamp_delta_seconds(a: PhotoItem, b: PhotoItem) -> int:
    if a.date_str != b.date_str or len(a.time_str) < 6 or len(b.time_str) < 6:
        return 1_000_000
    try:
        ta = int(a.time_str[:2]) * 3600 + int(a.time_str[2:4]) * 60 + int(a.time_str[4:6])
        tb = int(b.time_str[:2]) * 3600 + int(b.time_str[2:4]) * 60 + int(b.time_str[4:6])
    except ValueError:
        return 1_000_000
    return abs(ta - tb)


# ---------------------------------------------------------------------------
# Name templating
# ---------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"\{(?P<name>[a-zA-Z_]+)(?::(?P<fmt>[^}]+))?\}")
_LEGACY_TOKENS = {
    "[PK]": "{pk}",
    "[FECHA]": "{date}",
    "[HORA]": "{time}",
    "[ORIG]": "{original}",
}


def _normalize_template(template: str) -> str:
    """Replace legacy bracket tokens with the modern curly syntax."""
    if not template:
        return ""
    out = template
    for legacy, modern in _LEGACY_TOKENS.items():
        out = out.replace(legacy, modern)
    return out


def _sanitize_filename_fragment(text: str) -> str:
    """Strip filesystem-hostile characters while keeping unicode letters."""
    text = text.strip()
    text = re.sub(r"[\\/:*?\"<>|\0\r\n\t]+", "_", text)
    text = re.sub(r"_{2,}", "_", text)
    return text[:120]


def _contains_tokens(template: str) -> bool:
    return bool(_TOKEN_RE.search(template or ""))


def _load_cache(folder: str) -> Dict[str, Any]:
    path = os.path.join(folder, CACHE_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return {}
    entries = data.get("entries", {})
    return entries if isinstance(entries, dict) else {}


def _save_cache(folder: str, entries: Dict[str, Any]) -> None:
    path = os.path.join(folder, CACHE_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": CACHE_VERSION, "entries": entries}, f)
    except OSError as exc:
        logger.debug("Unable to persist EXIF cache in %s: %s", folder, exc)


def render_template(
    template: str,
    context: Dict[str, Any],
    sequence: int = 1,
) -> str:
    """Render a filename template against a mapping of token values.

    Unknown tokens are left untouched so the caller can debug them.  The
    ``sequence`` argument is injected as ``{sequence}`` / ``{seq}``.
    """
    if not template:
        template = "{pk}_{suffix}"
    template = _normalize_template(template)
    base_context = {
        "sequence": sequence,
        "seq": sequence,
    }
    base_context.update(context or {})

    def _replace(match: re.Match) -> str:
        name = match.group("name")
        fmt = match.group("fmt")
        if name not in base_context:
            return match.group(0)
        value = base_context[name]
        if value is None:
            value = ""
        try:
            return format(value, fmt) if fmt else str(value)
        except (ValueError, TypeError):
            return str(value)

    rendered = _TOKEN_RE.sub(_replace, template)
    return _sanitize_filename_fragment(rendered)


class RenamerLogic:
    def __init__(
        self,
        spatial_calc: SpatialCalculator,
        *,
        max_workers: int = DEFAULT_MAX_WORKERS,
        tukey_multiplier: float = DEFAULT_TUKEY_MULTIPLIER,
    ):
        self.spatial_calc = spatial_calc
        self.max_workers = max(1, int(max_workers))
        self.tukey_multiplier = float(tukey_multiplier)
        self._gps_cache: Dict[str, Any] = {}
        self.viaduct_pks: Set[str] = set()

    def set_viaduct_pks(self, pks: List[str]) -> None:
        """PK labels routed to VIADUCTOS/ (from June template or config)."""
        cleaned: Set[str] = set()
        for raw in pks or []:
            text = str(raw).upper().replace("PK", "").replace(" ", "").strip().lstrip("-")
            if text:
                cleaned.add(text)
        self.viaduct_pks = cleaned

    def enrich_item_spatial(self, item: PhotoItem) -> PhotoItem:
        """Fill nearest-PK / corridor distance / chainage / view on one item.

        Used by folder analysis and by SRT video import so both paths share
        the same spatial semantics (including landmark capture radius).
        """
        nearest_name, nearest_dist = self.spatial_calc.find_nearest_pk_name(item.lat, item.lon)
        item.nearest_name = nearest_name
        item.nearest_dist = nearest_dist
        item.distance = self.spatial_calc.corridor_distance(
            item.lat,
            item.lon,
            nearest_name=nearest_name,
            nearest_dist=nearest_dist,
        )
        item.pk_value = self.spatial_calc.calculate_pk(item.lat, item.lon)
        axis_bearing = self.spatial_calc.axis_bearing_at(item.lat, item.lon)
        item.view_label = classify_view(
            gimbal_yaw=item.gimbal_yaw,
            gimbal_pitch=item.gimbal_pitch,
            axis_bearing=axis_bearing,
        )
        return item

    def enrich_items_spatial(self, items: List[PhotoItem]) -> List[PhotoItem]:
        """Apply :meth:`enrich_item_spatial` to every item (in place)."""
        for item in items:
            self.enrich_item_spatial(item)
        return items

    # ------------------------------------------------------------------
    # EXIF extraction (tolerant + persistent cache)
    # ------------------------------------------------------------------
    def get_exif_data_from_image(self, path: str) -> Optional[Tuple[float, float, str, str]]:
        if path in self._gps_cache:
            return self._gps_cache[path]

        data = self._get_full_exif(path)
        if data is None:
            self._gps_cache[path] = None
            return None
        self._gps_cache[path] = (data["lat"], data["lon"], data["date"], data["time"])
        return self._gps_cache[path]

    def _get_full_exif(self, path: str) -> Optional[Dict[str, Any]]:
        """Return the extended EXIF payload used by analysis + cache."""
        try:
            with Image.open(path) as img:
                exif_blob = img.info.get("exif")
                if not exif_blob:
                    return None
                try:
                    exif_dict = piexif.load(exif_blob)
                except Exception:
                    return None

                gps_ifd = exif_dict.get("GPS", {}) or {}
                if not gps_ifd:
                    return None
                if piexif.GPSIFD.GPSLatitude not in gps_ifd or piexif.GPSIFD.GPSLongitude not in gps_ifd:
                    return None

                try:
                    lat = _convert_dms_to_dd(
                        gps_ifd[piexif.GPSIFD.GPSLatitude],
                        gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef, b"N"),
                    )
                    lon = _convert_dms_to_dd(
                        gps_ifd[piexif.GPSIFD.GPSLongitude],
                        gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef, b"E"),
                    )
                except (ValueError, ZeroDivisionError, TypeError) as exc:
                    logger.debug("Bad GPS data in %s: %s", path, exc)
                    return None

                date_str, time_str = "", ""
                exif_sub = exif_dict.get("Exif", {}) or {}
                dt_raw = exif_sub.get(piexif.ExifIFD.DateTimeOriginal)
                if dt_raw is None:
                    dt_raw = exif_sub.get(piexif.ExifIFD.DateTimeDigitized)
                if dt_raw is None:
                    dt_raw = exif_dict.get("0th", {}).get(piexif.ImageIFD.DateTime)
                if isinstance(dt_raw, bytes):
                    dt_raw = dt_raw.decode("utf-8", errors="ignore")
                if dt_raw:
                    date_str, time_str = _parse_exif_datetime(dt_raw)

                camera = ""
                make = exif_dict.get("0th", {}).get(piexif.ImageIFD.Make)
                model = exif_dict.get("0th", {}).get(piexif.ImageIFD.Model)
                parts: List[str] = []
                for raw in (make, model):
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="ignore").strip().rstrip("\x00")
                    if raw:
                        parts.append(str(raw).strip())
                if parts:
                    camera = " ".join(dict.fromkeys(parts))

                payload: Dict[str, Any] = {
                    "lat": lat,
                    "lon": lon,
                    "date": date_str,
                    "time": time_str,
                    "camera": camera,
                }
                # Reuse XMP already scanned by Pillow — avoid a second open/read
                # of up to 1 MiB per photo (dominant cost on cold / network I/O).
                xmp_blob = xmp_blob_from_pil(img)
                if xmp_blob is not None:
                    payload.update(orientation_payload(xmp=xmp_blob))
                else:
                    payload.update(orientation_payload())
                return payload
        except Exception as exc:
            logger.debug("Failed to read EXIF from %s: %s", path, exc)
        return None

    def analyze_distance_stats(
        self,
        folder: str,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Extrae fotos recursivamente y sugiere un umbral.

        Persistencia: tras un análisis completo se escribe
        ``.pk_exif_cache.json`` en la carpeta raíz con la extracción EXIF
        de cada foto, indexada por ruta + (mtime, size).  Los siguientes
        análisis reutilizan los registros válidos y solo releen del disco
        los archivos que han cambiado.  Desactívalo con ``use_cache=False``.
        """
        image_files, sidecar_index = collect_analysis_tree(folder)
        image_files.sort(key=_walked_image_path_sort_key)
        total = len(image_files)

        if total == 0:
            empty = compute_suggested_threshold([], tukey_multiplier=self.tukey_multiplier)
            empty["items"] = []
            empty["duplicates"] = 0
            return empty

        cache = _load_cache(folder) if use_cache else {}
        fresh_cache: Dict[str, Any] = {}
        cache_lock = threading.Lock()

        def _analyze_single(path: str) -> Optional[Tuple[PhotoItem, float]]:
            cached = cache.get(path)
            try:
                st = os.stat(path)
            except OSError:
                return None
            signature = [int(st.st_mtime), int(st.st_size)]

            exif_payload: Optional[Dict[str, Any]] = None
            if cached and cached.get("sig") == signature and cached.get("exif"):
                exif_payload = cached["exif"]
            else:
                exif_payload = self._get_full_exif(path)

            if not exif_payload:
                with cache_lock:
                    fresh_cache[path] = {"sig": signature, "exif": None}
                return None

            with cache_lock:
                fresh_cache[path] = {"sig": signature, "exif": exif_payload}

            lat = exif_payload["lat"]
            lon = exif_payload["lon"]
            date_str = exif_payload.get("date", "")
            time_str = exif_payload.get("time", "")
            camera = exif_payload.get("camera", "")
            gimbal_yaw = exif_payload.get("gimbal_yaw")
            gimbal_pitch = exif_payload.get("gimbal_pitch")
            gimbal_roll = exif_payload.get("gimbal_roll")
            flight_yaw = exif_payload.get("flight_yaw")
            rel_altitude = exif_payload.get("rel_altitude")

            item = PhotoItem(
                path=path,
                name=os.path.basename(path),
                lat=lat,
                lon=lon,
                date_str=date_str,
                time_str=time_str,
                camera=camera,
                gimbal_yaw=gimbal_yaw,
                gimbal_pitch=gimbal_pitch,
                gimbal_roll=gimbal_roll,
                flight_yaw=flight_yaw,
                rel_altitude=rel_altitude,
                sidecars=sidecar_index.find(path),
            )
            self.enrich_item_spatial(item)
            return item, item.distance


        items: List[PhotoItem] = []
        distances: List[float] = []
        completed = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_path = {executor.submit(_analyze_single, path): path for path in image_files}
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                completed += 1

                if progress_cb:
                    progress_cb(completed, total, f"Analizando {os.path.basename(path)}...")

                try:
                    result = future.result()
                except Exception:
                    result = None

                if not result:
                    continue

                item, dist_to_use = result
                items.append(item)
                if dist_to_use != float("inf"):
                    distances.append(dist_to_use)

        items.sort(key=photo_work_type_sort_key)

        duplicates = mark_duplicates(items)

        if use_cache:
            _save_cache(folder, fresh_cache)

        stats = compute_suggested_threshold(distances, tukey_multiplier=self.tukey_multiplier)
        stats["items"] = items
        stats["duplicates"] = duplicates
        return stats

    def sanitize_template(self, template: str) -> str:
        """Back-compat helper (legacy UI). Returns the template as-is,
        rendering is now done by :func:`render_template`."""
        return _normalize_template(template)[:120] if template else ""

    def sanitize_pk_name(self, name: str) -> str:
        s = re.sub(r"[^\w\+\-\s]", "", name)
        return s.strip()[:30]

    def build_preview_names(
        self,
        items: List[PhotoItem],
        threshold: float,
        template: str,
        *,
        landmark_threshold: Optional[float] = None,
    ) -> List[PhotoItem]:
        """Compute ``new_name_base`` for every item inside the threshold.

        Excluded items (``excluded=True``) are still inspected for threshold
        status (so the UI can show state) but skipped when writing the
        new name so they don't end up in the rename plan.
        """
        valid_items: List[PhotoItem] = []
        clean_template = _normalize_template(template.strip() if template else "") or "{pk}_{suffix}"
        lm_threshold = landmark_threshold if landmark_threshold and landmark_threshold > 0 else threshold

        for img in items:
            effective_threshold = (
                lm_threshold
                if self.spatial_calc.is_landmark_name(img.nearest_name)
                else threshold
            )
            img.is_inside_threshold = img.distance <= effective_threshold
            if not img.is_inside_threshold or img.excluded:
                img.new_name_base = ""
                continue
            if img.virtual:
                # Telemetry frames still count for coverage, but there is no
                # file to rename: planning one would target the .srt itself.
                img.new_name_base = ""
                img.pk_display = f"PK-{self.spatial_calc.format_pk_label(img.pk_value)}"
                continue

            use_interpolated = (
                self.spatial_calc.project_axis is not None
                and not self.spatial_calc.is_landmark_name(img.nearest_name)
            )

            if use_interpolated:
                # Continuous calibrated chainage (industry corridor practice)
                # instead of snapping every photo to the nearest PK placemark.
                clean_pk = self.spatial_calc.format_pk_label(img.pk_value)
                img.pk_display = f"PK-{clean_pk}"
            elif img.nearest_name:
                clean_pk = (
                    self.sanitize_pk_name(img.nearest_name)
                    .upper()
                    .replace("PK", "")
                    .strip()
                    .lstrip("-+")
                    .strip()
                )
                img.pk_display = img.nearest_name
            else:
                clean_pk = self.spatial_calc.format_pk_label(img.pk_value)
                img.pk_display = f"PK-{clean_pk}"

            # Separate the suffix the user may have typed as a plain literal.
            # The legacy UI treats ``template`` as the suffix appended to the
            # PK; we keep both mental models working by injecting it as a
            # ``{suffix}`` token so templates like ``{pk}_{suffix}`` still do
            # the right thing.
            suffix_for_token = "" if _contains_tokens(clean_template) else template.strip()
            effective_template = clean_template if _contains_tokens(clean_template) else (
                "{pk}_{suffix}" if suffix_for_token else "{pk}"
            )
            original_stem = os.path.splitext(img.name)[0]
            view = (img.view_label or "").upper()
            # Append TI/TD/CEN only for side/nadir shots so traza names stay clean.
            pk_token = f"PK-{clean_pk}"
            if view in ("TI", "TD", "CEN") and not self.spatial_calc.is_landmark_name(img.nearest_name):
                pk_token = f"PK-{clean_pk}-{view}"

            km_val = int(img.pk_value // 1000) if img.pk_value else 0
            m_val = int(img.pk_value % 1000) if img.pk_value else 0
            if "+" in clean_pk:
                parts = clean_pk.split("+", 1)
                try:
                    km_val = int(parts[0])
                    m_val = int(parts[1])
                except ValueError:
                    pass

            context = {
                "pk": pk_token,

                "pk_raw": clean_pk,
                "km": km_val,
                "m": f"{m_val:03d}",
                "suffix": suffix_for_token or template.strip(),
                "date": img.date_str or "SinFecha",
                "time": img.time_str or "SinHora",
                "original": original_stem,
                "camera": img.camera or "",
                "view": view,
                "lat": f"{img.lat:.6f}",
                "lon": f"{img.lon:.6f}",
                "dist": f"{img.distance:.2f}" if img.distance != float("inf") else "",
                "alt": f"{img.rel_altitude:.1f}" if img.rel_altitude is not None else "",
            }
            final_base = render_template(effective_template, context)
            final_base = re.sub(r"[-_]{2,}", "-", final_base).strip("-_")
            img.new_name_base = final_base
            valid_items.append(img)

        return valid_items


    def ensure_work_folders(
        self,
        base_folder: str,
        *,
        landmark_names: Optional[List[str]] = None,
    ) -> List[str]:
        """Create June-style work folders even when they stay empty.

        Always ensures ``OTROS``, ``VIADUCTOS`` and ``VERTEDEROS``. Under
        ``VERTEDEROS`` creates one subfolder per configured landmark / group.
        Returns the list of paths that were created or already existed.
        """
        if not base_folder or not os.path.isdir(base_folder):
            return []

        created: List[str] = []
        roots = ("OTROS", "VIADUCTOS", "VERTEDEROS")
        for name in roots:
            path = os.path.join(base_folder, name)
            os.makedirs(path, exist_ok=True)
            created.append(path)

        vertederos_root = os.path.join(base_folder, "VERTEDEROS")
        subfolders: List[str] = []

        # Prefer explicit landmark group folders (e.g. Caliche-Palomares).
        for group in getattr(self.spatial_calc, "_landmark_groups", []) or []:
            folder = str(group.get("folder") or group.get("name") or "").strip()
            if folder:
                subfolders.append(folder)

        # Individual landmarks not already covered by a group folder.
        grouped_members = {
            m.strip().casefold()
            for group in getattr(self.spatial_calc, "_landmark_groups", []) or []
            for m in (group.get("members") or [])
            if str(m).strip()
        }
        names = landmark_names or []
        if not names:
            for pt in getattr(self.spatial_calc, "named_points", []) or []:
                if self.spatial_calc.is_landmark_name(pt.name):
                    names.append(pt.name)
            # Also include landmark name keys even if points were deduped from KML.
            for key in getattr(self.spatial_calc, "_landmark_names", set()) or set():
                if key in grouped_members:
                    continue
                # Prefer original casing from named_points when available.
                match = next(
                    (
                        pt.name
                        for pt in getattr(self.spatial_calc, "named_points", []) or []
                        if pt.name.strip().casefold() == key
                    ),
                    key,
                )
                names.append(match)

        for name in names:
            clean = str(name).strip()
            if not clean:
                continue
            if clean.casefold() in grouped_members:
                continue
            # Skip group labels themselves (already added above).
            if any(
                clean.casefold() == str(g.get("name", "")).strip().casefold()
                or clean.casefold() == str(g.get("folder", "")).strip().casefold()
                for g in getattr(self.spatial_calc, "_landmark_groups", []) or []
            ):
                continue
            subfolders.append(clean)

        # Deduplicate preserving order.
        seen: Set[str] = set()
        for folder in subfolders:
            key = folder.casefold()
            if key in seen:
                continue
            seen.add(key)
            path = safe_join_under(vertederos_root, folder)
            if path is None:
                logger.warning(
                    "Landmark folder rechazado (fuera del árbol de trabajo): %r",
                    folder,
                )
                continue
            os.makedirs(path, exist_ok=True)
            created.append(path)

        return created

    def resolve_output_dir(self, item: PhotoItem, base_folder: str) -> str:
        """Choose destination folder (June-style VERTEDEROS/VIADUCTOS/traza)."""
        landmark_folder = self.spatial_calc.get_landmark_folder(item.nearest_name)
        if landmark_folder:
            # Grouped landmarks already provide their folder name.
            if self.spatial_calc.is_landmark_name(item.nearest_name):
                # Put landmark groups under VERTEDEROS/ unless already nested.
                if landmark_folder.upper().startswith("VERTEDEROS"):
                    safe = safe_join_under(base_folder, landmark_folder)
                else:
                    safe = safe_join_under(base_folder, "VERTEDEROS", landmark_folder)
                if safe is None:
                    logger.warning(
                        "Landmark folder inseguro %r; se usa la carpeta base.",
                        landmark_folder,
                    )
                    return base_folder
                return safe
            safe = safe_join_under(base_folder, landmark_folder)
            if safe is None:
                logger.warning(
                    "Landmark folder inseguro %r; se usa la carpeta base.",
                    landmark_folder,
                )
                return base_folder
            return safe

        view = (item.view_label or "").upper()
        if view in ("TI", "TD", "CEN"):
            return os.path.join(base_folder, "VIADUCTOS")

        pk_key = ""
        if item.nearest_name and not self.spatial_calc.is_landmark_name(item.nearest_name):
            pk_key = (
                self.sanitize_pk_name(item.nearest_name)
                .upper()
                .replace("PK", "")
                .replace(" ", "")
                .lstrip("-+")
                .strip()
            )
        if not pk_key and item.pk_value:
            km = int(item.pk_value // 1000)
            m = int(item.pk_value % 1000)
            pk_key = f"{km}+{m:03d}"
        if pk_key and pk_key in self.viaduct_pks:
            return os.path.join(base_folder, "VIADUCTOS")
        return base_folder

    def relative_output_dir(self, item: PhotoItem, base_folder: str) -> str:
        """Return a portable relative destination label for UI / reports.

        ``"."`` / empty → ``"(raíz)"``. Uses forward slashes so the same
        string is readable on every OS.
        """
        if not base_folder:
            return "(raíz)"
        target = self.resolve_output_dir(item, base_folder)
        rel = relative_mapping_key(target, base_folder)
        if not rel or rel == ".":
            return "(raíz)"
        return rel

    def assign_destination_folders(
        self,
        items: List[PhotoItem],
        base_folder: str,
    ) -> List[PhotoItem]:
        """Stamp ``dest_rel`` on every item (in place) for preview / export."""
        for item in items:
            if item.excluded or not item.is_inside_threshold or not item.new_name_base:
                item.dest_rel = ""
            else:
                item.dest_rel = self.relative_output_dir(item, base_folder)
        return items

    def write_metadata(self, path: str, pk_text: str) -> bool:
        """Inject EXIF UserComment without recompressing JPEG pixels.

        JPEG writes are atomic: EXIF (and optional XMP reinject) land on a
        temp sibling first, then ``os.replace`` promotes them. The live file
        is never truncated in place, matching the XMP inject hardening.

        Returns ``True`` when metadata was written (or there was nothing to do
        for an unsupported extension), ``False`` when a JPEG write/inject
        failed. Callers that already renamed the file should treat ``False``
        as an error so corrupt/partial writes are not reported as success.
        """
        try:
            if not path or not os.path.isfile(path):
                return False
            ext = os.path.splitext(path)[1].lower()
            if ext in (".jpg", ".jpeg"):
                return self._write_jpeg_metadata_atomic(path, pk_text)
            if ext in (".tif", ".tiff", ".webp"):
                # Avoid re-encoding production TIFFs/WebPs (lossy / multipage risk).
                logger.debug("Omitiendo escritura de metadatos en %s (formato no-JPEG)", path)
                return True
            return True
        except Exception as e:
            logger.warning("Failed to write metadata for %s: %s", path, e)
            return False

    def _write_jpeg_metadata_atomic(self, path: str, pk_text: str) -> bool:
        """Write UserComment (+ preserve XMP) via temp file + ``os.replace``."""
        xmp_segment = extract_jpeg_xmp_packet(path)
        try:
            exif_dict = piexif.load(path)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        exif_dict.setdefault("Exif", {})
        if piexif_helper is not None:
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = piexif_helper.UserComment.dump(
                pk_text, encoding="unicode"
            )
        else:
            exif_dict["Exif"][piexif.ExifIFD.UserComment] = pk_text.encode("utf-8")

        tmp_path = f"{path}.__exif_tmp__"
        try:
            try:
                exif_bytes = piexif.dump(exif_dict)
                # Write to a sibling temp so a mid-write crash cannot zero the
                # live JPEG (piexif.insert truncates when writing in place).
                piexif.insert(exif_bytes, path, new_file=tmp_path)
            except Exception as exc:
                logger.warning("Fallo piexif.insert en %s: %s", path, exc)
                _safe_unlink(tmp_path)
                return False

            try:
                with open(tmp_path, "rb+") as fh:
                    fh.flush()
                    os.fsync(fh.fileno())
            except OSError as exc:
                logger.warning("Fallo fsync EXIF tmp en %s: %s", path, exc)
                _safe_unlink(tmp_path)
                return False

            if xmp_segment:
                if not inject_jpeg_xmp_packet(tmp_path, xmp_segment):
                    logger.warning("Fallo inject_jpeg_xmp_packet en %s", path)
                    _safe_unlink(tmp_path)
                    return False

            try:
                os.replace(tmp_path, path)
            except OSError as exc:
                logger.warning("Fallo os.replace EXIF en %s: %s", path, exc)
                _safe_unlink(tmp_path)
                return False
            return True
        except Exception as exc:
            logger.warning("Failed atomic JPEG metadata for %s: %s", path, exc)
            _safe_unlink(tmp_path)
            return False

    def process_images(self, 
            items: List[PhotoItem], 
            base_folder: str, 
            create_backup: bool, 
            progress_cb: Callable[[int, int, str], None], 
            check_cancel: Callable[[], bool]) -> RenameStats:
            
        backup_folder = os.path.join(base_folder, "_backup_originales")
        if create_backup:
            os.makedirs(backup_folder, exist_ok=True)

        # Always materialize the June-style folder tree (even if empty).
        self.ensure_work_folders(base_folder)
            
        csv_path = str(report_csv_path(base_folder))
        
        jobs = self._build_rename_jobs(items)
        
        total = len(jobs)
        completed = 0
        results_csv = []
        stats = {"ok": 0, "errors": 0, "skipped": 0, "cancelled": 0}

        if total == 0:
            progress_cb(0, 0, "No hay archivos válidos para procesar.")
            stats["mapping"] = {}
            return stats
        
        def _process_single(job: Tuple[PhotoItem, str]):
            item, new_name = job
            orig_path = item.path
            orig_name = item.name
            target_dir = self.resolve_output_dir(item, base_folder)
            os.makedirs(target_dir, exist_ok=True)
            new_path = os.path.join(target_dir, new_name)
            new_stem = os.path.splitext(new_name)[0]
            orig_rel = relative_mapping_key(orig_path, base_folder)
            new_rel = relative_mapping_key(new_path, base_folder)
            base_fields = {
                "original": orig_rel,
                "nuevo": new_rel,
                "pk": item.pk_display,
                "distancia": f"{item.distance:.2f}",
            }

            try:
                # Collision check before backup so a skipped job does not
                # leave a misleading backup copy.
                if orig_path != new_path and os.path.exists(new_path):
                    return {
                        **base_fields,
                        "status": "skipped",
                        "error": f"Destino ya existe: {new_name}",
                    }

                # Preflight sidecar destinations so we never orphan companions
                # after a successful photo rename.
                sidecar_plan: List[Tuple[str, str]] = []
                # Companions already sitting at their final path: they need no
                # move but still belong to the photo's sidecar list afterwards.
                sidecar_static: List[str] = []
                for sc_path in list(item.sidecars):
                    if not os.path.exists(sc_path):
                        continue
                    sc_ext = os.path.splitext(sc_path)[1]
                    sc_new = os.path.join(target_dir, new_stem + sc_ext)
                    if sc_path == sc_new:
                        sidecar_static.append(sc_path)
                        continue
                    if os.path.exists(sc_new):
                        return {
                            **base_fields,
                            "status": "skipped",
                            "error": (
                                f"Sidecar destino ya existe: {os.path.basename(sc_new)}"
                            ),
                        }
                    sidecar_plan.append((sc_path, sc_new))

                if create_backup:
                    # Mirror the *source* tree so two DJI_0001.jpg from different
                    # input folders never overwrite each other under backup.
                    _copy_backup_original(orig_path, base_folder, backup_folder)
                    for sc_path, _sc_new in sidecar_plan:
                        if os.path.exists(sc_path):
                            _copy_backup_original(sc_path, base_folder, backup_folder)

                photo_moved = False
                if orig_path != new_path:
                    os.rename(orig_path, new_path)
                    photo_moved = True

                # Prefer the final filename stem so EXIF matches the FS name
                # including sequence suffixes (_01, _02, …).
                if not self.write_metadata(new_path, new_stem):
                    rolled_back = True
                    if photo_moved:
                        rolled_back = _try_rename(new_path, orig_path)
                    result = {
                        **base_fields,
                        "status": "error",
                        "error": "Fallo al escribir metadatos EXIF/XMP",
                        "new_path": new_path if not rolled_back else None,
                    }
                    if not rolled_back:
                        # Disk kept the new name: move companions too so they
                        # are not orphaned next to the old path, and expose
                        # the full mapping so undo can reverse both.
                        result["record_mapping"] = True
                        stuck_sidecars: List[Tuple[str, str]] = []
                        moved_sidecars: List[str] = []
                        for sc_path, sc_new in sidecar_plan:
                            if not os.path.exists(sc_path):
                                continue
                            if _try_rename(sc_path, sc_new):
                                moved_sidecars.append(sc_new)
                                stuck_sidecars.append(
                                    (
                                        relative_mapping_key(sc_path, base_folder),
                                        relative_mapping_key(sc_new, base_folder),
                                    )
                                )
                        result["sidecars"] = stuck_sidecars
                        item.path = new_path
                        item.name = new_name
                        # Derived from the plan we just executed — re-scanning
                        # the directory here costs one listing per photo.
                        item.sidecars = sidecar_static + moved_sidecars
                    return result

                renamed_sidecars: List[Tuple[str, str]] = []
                renamed_sidecar_paths: List[Tuple[str, str]] = []
                for sc_path, sc_new in sidecar_plan:
                    # Sidecar may still sit next to the *original* photo dir
                    # (same folder rename) or already be at sc_path.
                    if not os.path.exists(sc_path):
                        continue
                    if not _try_rename(sc_path, sc_new):
                        # Roll back photo + any sidecars already moved. A
                        # companion whose rollback also fails stays at its new
                        # path, so only those may be recorded for undo.
                        still_moved: List[Tuple[str, str]] = []
                        for done_old, done_new in reversed(renamed_sidecar_paths):
                            if not _try_rename(done_new, done_old):
                                still_moved.append((done_old, done_new))
                        still_moved.reverse()
                        rolled_back = True
                        if photo_moved:
                            rolled_back = _try_rename(new_path, orig_path)
                        result = {
                            **base_fields,
                            "status": "error",
                            "error": (
                                f"Fallo renombrando sidecar: "
                                f"{os.path.basename(sc_path)}"
                            ),
                            "new_path": new_path if not rolled_back else None,
                        }
                        if not rolled_back:
                            result["record_mapping"] = True
                            result["sidecars"] = [
                                (
                                    relative_mapping_key(o, base_folder),
                                    relative_mapping_key(n, base_folder),
                                )
                                for o, n in still_moved
                            ]
                            item.path = new_path
                            item.name = new_name
                            item.sidecars = sidecar_static + [
                                n for _o, n in still_moved
                            ]
                        return result
                    renamed_sidecar_paths.append((sc_path, sc_new))
                    renamed_sidecars.append(
                        (
                            relative_mapping_key(sc_path, base_folder),
                            relative_mapping_key(sc_new, base_folder),
                        )
                    )

                # Keep in-memory items coherent for a second F7 / session save.
                item.path = new_path
                item.name = new_name
                item.sidecars = sidecar_static + [n for _o, n in renamed_sidecar_paths]

                return {
                    **base_fields,
                    "status": "ok",
                    "sidecars": renamed_sidecars,
                }
            except Exception as e:
                return {
                    **base_fields,
                    "status": "error",
                    "error": str(e),
                }

        # Sequential FS ops: every completed job is recorded before the next
        # cancel check, so partial batches remain undoable via CSV/mapping.
        for job in jobs:
            if check_cancel():
                remaining = total - completed
                stats["cancelled"] += remaining
                progress_cb(completed, total, "Cancelado")
                break

            res = _process_single(job)

            if res and res.get('status') == 'ok':
                stats["ok"] += 1
                results_csv.append({
                    'original': res.get('original', ''),
                    'nuevo': res.get('nuevo', ''),
                    'pk': res.get('pk', ''),
                    'distancia': res.get('distancia', '')
                })
                for sc_old, sc_new in res.get("sidecars") or []:
                    results_csv.append({
                        "original": sc_old,
                        "nuevo": sc_new,
                        "pk": res.get("pk", ""),
                        "distancia": res.get("distancia", ""),
                    })
            elif res and res.get('status') == 'skipped':
                stats["skipped"] += 1
            elif res and res.get('status') == 'error':
                stats["errors"] += 1
                # If the file stayed renamed after a failed rollback, keep it
                # in the undo map so the operator can still reverse it.
                if res.get("record_mapping") and res.get("nuevo"):
                    results_csv.append({
                        "original": res.get("original", ""),
                        "nuevo": res.get("nuevo", ""),
                        "pk": res.get("pk", ""),
                        "distancia": res.get("distancia", ""),
                    })
                    for sc_old, sc_new in res.get("sidecars") or []:
                        results_csv.append({
                            "original": sc_old,
                            "nuevo": sc_new,
                            "pk": res.get("pk", ""),
                            "distancia": res.get("distancia", ""),
                        })

            completed += 1
            if res and res.get('status') == 'skipped':
                progress_cb(completed, total, f"Omitido: {res.get('error', 'conflicto de nombre')}")
            elif res and res.get('status') == 'error':
                progress_cb(completed, total, f"Error: {res.get('error', 'fallo desconocido')}")
            else:
                progress_cb(completed, total, f"Procesando: {res['nuevo']}")
                    
        if results_csv:
            save_rename_report(base_folder, results_csv)
            stats["mapping"] = {
                row["nuevo"]: row["original"] for row in results_csv if row.get("nuevo")
            }
        else:
            stats["mapping"] = {}
        return stats


    def _build_rename_jobs(self, items: List[PhotoItem]) -> List[Tuple[PhotoItem, str]]:
        """Genera el plan de renombrado con agrupación automática por PK.

        - Fotos excluidas manualmente se descartan.
        - Fotos fuera del umbral se descartan.
        - Las fotos que comparten ``new_name_base`` se ordenan por timestamp
          EXIF; a igualdad de tiempo, por tipo de obra (carpetas) y nombre.
          Se numeran ``_01``, ``_02``... para que las ráfagas sobre el mismo
          PK queden cronológicas sin colisiones.
        """
        pk_groups: Dict[str, List[PhotoItem]] = {}
        for item in items:
            if not item.is_inside_threshold or item.excluded:
                continue
            # Belt and braces: ``build_preview_names`` already leaves virtual
            # frames without a base name, but F7 must never touch a path that
            # does not name a real file.
            if item.virtual or not item.new_name_base:
                continue
            pk_groups.setdefault(item.new_name_base, []).append(item)

        jobs: List[Tuple[PhotoItem, str]] = []
        # Process PK groups in chainage order so the rename plan itself "flies"
        # along the traza (and TI → CEN → TD at each PK when orientation exists).
        ordered_groups = sorted(
            pk_groups.items(),
            key=lambda kv: (
                min((it.pk_value for it in kv[1]), default=0.0),
                kv[0].casefold(),
            ),
        )
        for _, group in ordered_groups:
            group.sort(
                key=lambda x: (
                    float(x.pk_value or 0.0),
                    view_sort_rank(x.view_label),
                    x.date_str or "",
                    x.time_str or "",
                    *path_work_type_sort_prefix(x.path),
                    x.name.casefold(),
                )
            )
            multiple = len(group) > 1
            for seq, item in enumerate(group, start=1):
                original_ext = os.path.splitext(item.name)[1].lower() or ".jpg"
                if multiple:
                    new_name = f"{item.new_name_base}_{seq:02d}{original_ext}"
                else:
                    new_name = f"{item.new_name_base}{original_ext}"
                jobs.append((item, new_name))
        return jobs

    def build_preview_plan(
        self,
        items: List[PhotoItem],
        base_folder: str = "",
    ) -> Dict[str, str]:
        """Return ``path -> final filename`` matching the real F7 rename plan.

        Includes sequence suffixes (``_01``) and the extension. Destination
        folders are exposed separately via ``assign_destination_folders`` /
        ``dest_rel`` so the preview table can show Destino in its own column.
        ``base_folder`` is accepted for API compatibility with callers that
        already pass it; it does not affect the filename labels.
        """
        del base_folder  # reserved for callers; destination is on dest_rel
        return {
            item.path: new_name
            for item, new_name in self._build_rename_jobs(items)
        }

    def get_rename_plan(self, items: List[PhotoItem], base_folder: str) -> Dict[str, int]:
        """Devuelve un pre-chequeo de seguridad antes de renombrar.

        Counts photo-target collisions and sidecar-target collisions as
        conflicts so the F7 confirm dialog matches what ``process_images``
        will actually skip.
        """
        jobs = self._build_rename_jobs(items)
        conflicts = 0
        photo_conflicts = 0
        sidecar_conflicts = 0
        unchanged = 0
        for item, new_name in jobs:
            orig_path = item.path
            target_dir = self.resolve_output_dir(item, base_folder)
            new_path = os.path.join(target_dir, new_name)
            new_stem = os.path.splitext(new_name)[0]
            if orig_path == new_path:
                unchanged += 1

            job_conflict = False
            if orig_path != new_path and os.path.exists(new_path):
                photo_conflicts += 1
                job_conflict = True
            else:
                for sc_path in list(item.sidecars):
                    if not os.path.exists(sc_path):
                        continue
                    sc_ext = os.path.splitext(sc_path)[1]
                    sc_new = os.path.join(target_dir, new_stem + sc_ext)
                    if sc_path == sc_new:
                        continue
                    if os.path.exists(sc_new):
                        sidecar_conflicts += 1
                        job_conflict = True
                        break

            if job_conflict:
                conflicts += 1

        return {
            "total": len(jobs),
            "conflicts": conflicts,
            "photo_conflicts": photo_conflicts,
            "sidecar_conflicts": sidecar_conflicts,
            "unchanged": unchanged,
            "effective": max(0, len(jobs) - conflicts),
        }

    def undo_last_rename_from_csv(
        self,
        base_folder: str,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> Tuple[bool, str]:
        """Revert the last rename batch using ``reporte_renombrado.csv``.

        Supports legacy basename-only rows and relative-path rows produced by
        current builds (files restored to their original folders).
        """
        if not report_csv_path(base_folder).is_file():
            return False, f"No se encontró ningún {RENAME_REPORT_FILENAME} en esta carpeta."

        operations = load_rename_operations(base_folder)
        if not operations:
            return False, "El archivo CSV está vacío."

        total = len(operations)
        if progress_cb:
            progress_cb(0, total, "Revirtiendo renombrado…")

        summary = undo_rename_operations(base_folder, operations)
        reversed_count = int(summary.get("ok", 0))
        failed_count = int(summary.get("missing", 0)) + int(summary.get("conflict", 0))

        if progress_cb:
            progress_cb(total, total, "Reversión completada.")

        if reversed_count == 0:
            return False, (
                f"No se pudo revertir ningún archivo ({total} en el informe, "
                f"{failed_count} errores)."
            )
        msg = f"Se han revertido {reversed_count} de {total} archivos."
        if failed_count:
            msg += f" ({failed_count} omitidos por error o conflicto.)"
        return True, msg
