"""Recognising what a KML is for.

Every client folder holds several KML and only one is the trace. Measured on
the real share (23 files), they fall into four kinds that can be told apart by
what they contain, not by what they are called:

* **trace** -- hundreds of placemarks named like a chainage post
  (``Puntos para script.kml``: 180 of them).
* **landmarks** -- a handful of named points that are *not* posts
  (``Vertederos.kml``: ``TP01``).
* **survey** -- the client's own drawing: polygons, or 123 401 LineStrings with
  a few posts scattered through it (``66835 Riquelme_Torre Pacheco.kml``,
  27 MB). It has enough PK-named points to pass for a trace and is not one.
* **empty** -- 0 bytes (``Ortofoto.kml``, ``MDS.kml``).

Choosing the wrong one used to be silent and put the whole delivery at PK-0+000
(v3.9.2 now warns); this recognises the right one up front so the operator is
not asked to.

Qt-free, read-only: it only ever opens files for reading, and it never looks
inside the photo folders.
"""
from __future__ import annotations

import logging
import os
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from lxml import etree

from .spatial_calculator import SpatialCalculator

logger = logging.getLogger(__name__)

ROLE_TRACE = "trace"
ROLE_LANDMARKS = "landmarks"
ROLE_SURVEY = "survey"
ROLE_EMPTY = "empty"
ROLE_UNREADABLE = "unreadable"

ROLE_LABELS = {
    ROLE_TRACE: "traza",
    ROLE_LANDMARKS: "vertederos",
    ROLE_SURVEY: "levantamiento / otros",
    ROLE_EMPTY: "vacío",
    ROLE_UNREADABLE: "ilegible",
}

#: Fewest chainage posts for a file to count as a trace. The smallest real one
#: has 180; anything with fewer is a landmark or drawing file that happens to
#: contain a number-looking name.
MIN_PK_POSTS = 10

#: Above this the file is read but not loaded into a SpatialCalculator to
#: verify it: the check costs roughly the parse time again. The largest real
#: file is 27 MB.
VERIFY_MAX_BYTES = 120 * 1024 * 1024

#: Names kept for display; a trace has hundreds of landmarks-looking noise and
#: the summary only ever shows a few.
_MAX_NAMES = 40

_KML_SUFFIXES = (".kml", ".kmz")
#: Sub-folders worth looking into: the real tree keeps some KML in ``kml/``.
_KML_SUBDIRS = ("kml", "kmz")


@dataclass
class KmlProfile:
    """What one KML contains, and what that makes it."""

    path: str
    role: str
    reason: str = ""
    size_bytes: int = 0
    modified: float = 0.0
    pk_posts: int = 0
    landmark_points: int = 0
    linestrings: int = 0
    polygons: int = 0
    pk_min_m: Optional[float] = None
    pk_max_m: Optional[float] = None
    landmark_names: Tuple[str, ...] = ()
    folders: Tuple[str, ...] = ()
    #: None = not verified (landmark/empty files, or too large to load).
    trace_verified: Optional[bool] = None
    #: Median error of the trace against its own anchors, when verified.
    residual_m: Optional[float] = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def is_trace(self) -> bool:
        return self.role == ROLE_TRACE

    def span_label(self) -> str:
        if self.pk_min_m is None or self.pk_max_m is None:
            return ""
        fmt = SpatialCalculator.format_pk_label
        return f"{fmt(self.pk_min_m)}–{fmt(self.pk_max_m)}"

    def summary(self) -> str:
        """One line for a dialog or a tooltip, in Spanish."""
        label = ROLE_LABELS.get(self.role, self.role)
        if self.role == ROLE_TRACE:
            return f"{label} · {self.pk_posts} PK ({self.span_label()})"
        if self.role == ROLE_LANDMARKS:
            nombres = ", ".join(self.landmark_names[:5])
            return f"{label} · {nombres}" if nombres else label
        if self.reason:
            return f"{label} · {self.reason}"
        return label


@dataclass
class KmlRecommendation:
    """What to use from a set of candidate files."""

    trace: Optional[KmlProfile] = None
    #: Other files that are equally valid traces (same job, kept in sync by hand).
    alternatives: List[KmlProfile] = field(default_factory=list)
    landmark_kmls: List[KmlProfile] = field(default_factory=list)
    ignored: List[KmlProfile] = field(default_factory=list)

    @property
    def landmark_paths(self) -> List[str]:
        return [p.path for p in self.landmark_kmls]


# ---------------------------------------------------------------------------
# Profiling one file
# ---------------------------------------------------------------------------
def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _open_kml(path: str):
    """Return a binary file object for the KML inside ``path`` (.kml or .kmz)."""
    if path.lower().endswith(".kmz"):
        archive = zipfile.ZipFile(path, "r")
        for entry in archive.namelist():
            if entry.lower().endswith(".kml"):
                return archive.open(entry)
        archive.close()
        raise ValueError("el KMZ no contiene ningún .kml")
    return open(path, "rb")


def _scan(path: str, profile: KmlProfile) -> None:
    """Stream the file once, counting what is in it.

    ``iterparse`` and clearing each placemark as it is read keeps a 27 MB file
    with 125 000 geometries at a flat memory cost instead of building the tree.
    """
    pk_values: List[float] = []
    names: List[str] = []
    folder_names: List[str] = []
    seen_folders = set()

    with _open_kml(path) as handle:
        for _event, el in etree.iterparse(handle, events=("end",), recover=True, huge_tree=True):
            tag = _local(el.tag)
            if tag == "Placemark":
                name = ""
                points = 0
                for child in el.iter():
                    t = _local(child.tag)
                    if t == "name" and not name and child.getparent() is el:
                        name = (child.text or "").strip()
                    elif t == "Point":
                        points += 1
                    elif t == "LineString":
                        profile.linestrings += 1
                    elif t == "Polygon":
                        profile.polygons += 1
                if points:
                    pk = SpatialCalculator.parse_pk_name(name)
                    if pk is not None:
                        profile.pk_posts += 1
                        pk_values.append(pk)
                    else:
                        profile.landmark_points += points
                        if name and name not in names and len(names) < _MAX_NAMES:
                            names.append(name)
                # Free what has been consumed; a trace file is mostly geometry.
                el.clear()
                while el.getprevious() is not None:
                    parent = el.getparent()
                    if parent is None:
                        break
                    del parent[0]
            elif tag == "name":
                # Read at the name's own end event: the clean-up above deletes
                # earlier siblings of each placemark, a folder's <name> among
                # them, so it cannot wait for the folder to close.
                parent = el.getparent()
                if parent is not None and _local(parent.tag) == "Folder":
                    label = (el.text or "").strip()
                    if label and label not in seen_folders:
                        seen_folders.add(label)
                        folder_names.append(label)

    if pk_values:
        profile.pk_min_m, profile.pk_max_m = min(pk_values), max(pk_values)
    profile.landmark_names = tuple(names)
    profile.folders = tuple(folder_names)


def _verify_trace(path: str, profile: KmlProfile) -> None:
    """Confirm a trace candidate really reproduces its own chainage.

    Reuses the calibration check of the calculator rather than a second
    heuristic: on the real share the trace scores 0.00 m over its anchors and
    the survey file, which also carries 370 PK-named points, scores 18 553 m.
    """
    if profile.size_bytes > VERIFY_MAX_BYTES:
        return
    try:
        calc = SpatialCalculator()
        calc.load_kml(path)
    except Exception as exc:
        profile.role = ROLE_UNREADABLE
        profile.reason = f"no carga: {type(exc).__name__}"
        return
    if not calc.has_axis():
        profile.role = ROLE_SURVEY
        profile.reason = "no produce una traza"
        profile.trace_verified = False
        return
    profile.residual_m = calc.calibration_residual_m()
    if calc.axis_looks_trustworthy():
        # An axis inferred from the posts themselves has no residual to judge:
        # it passes through them by construction, so say "unverified", not "ok".
        profile.trace_verified = True if profile.residual_m is not None else None
    else:
        profile.role = ROLE_SURVEY
        profile.trace_verified = False
        profile.reason = (
            f"su geometría se desvía {profile.residual_m:.0f} m de sus propios PK"
            if profile.residual_m is not None else "su geometría no sigue los PK"
        )


def profile_kml(path: str, *, verify: bool = True) -> KmlProfile:
    """Classify one KML/KMZ by content. Never raises."""
    profile = KmlProfile(path=path, role=ROLE_UNREADABLE)
    try:
        stat = os.stat(path)
        profile.size_bytes, profile.modified = stat.st_size, stat.st_mtime
    except OSError as exc:
        profile.reason = f"no accesible ({exc.__class__.__name__})"
        return profile
    if profile.size_bytes == 0:
        profile.role, profile.reason = ROLE_EMPTY, "0 bytes"
        return profile

    try:
        _scan(path, profile)
    except Exception as exc:  # lxml/zip/OS: a bad file must not stop a scan of 23
        logger.warning("No se pudo analizar %s: %s", path, exc)
        profile.reason = f"no se puede leer ({exc.__class__.__name__})"
        return profile

    total = profile.pk_posts + profile.landmark_points
    if total == 0 and not profile.linestrings and not profile.polygons:
        profile.role, profile.reason = ROLE_EMPTY, "sin geometrías"
    elif profile.pk_posts >= MIN_PK_POSTS:
        profile.role = ROLE_TRACE
        if verify:
            _verify_trace(path, profile)
    elif profile.landmark_points and profile.landmark_points >= (profile.polygons + profile.linestrings):
        profile.role = ROLE_LANDMARKS
    else:
        profile.role = ROLE_SURVEY
        parts = []
        if profile.polygons:
            parts.append(f"{profile.polygons} polígonos")
        if profile.linestrings:
            parts.append(f"{profile.linestrings} líneas")
        profile.reason = ", ".join(parts) or "sin puntos de PK"
    return profile


# ---------------------------------------------------------------------------
# Finding and choosing the files of one job
# ---------------------------------------------------------------------------
def _kml_files_in(directory: str) -> List[str]:
    """KML/KMZ directly in ``directory`` and in a ``kml/`` sub-folder.

    Deliberately shallow: the folder being looked at is a delivery with
    thousands of photos over SMB, and walking it is exactly the cost this app
    works to avoid.
    """
    found: List[str] = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    if entry.is_file() and entry.name.lower().endswith(_KML_SUFFIXES):
                        found.append(entry.path)
                    elif entry.is_dir() and entry.name.lower() in _KML_SUBDIRS:
                        found.extend(_kml_files_in(entry.path))
                except OSError:
                    continue
    except OSError:
        pass
    return found


def candidate_directories(folder: str, *, max_levels: int = 3) -> List[str]:
    """``folder`` and its ancestors up to the job root, nearest first.

    The tree is ``…/CLIENTES/<obra>/<año>/<mes>``: the KML live at ``<obra>``,
    two levels above the delivery. Stops at the job root when it is
    recognisable and never climbs past ``max_levels``.
    """
    if not folder:
        return []
    from .projects import guess_project_root  # local: projects imports this package

    root = None
    guessed = guess_project_root(folder)
    if guessed:
        root = os.path.normcase(os.path.normpath(guessed[0]))
    path = Path(os.path.normpath(folder))
    if path.is_file():
        path = path.parent
    out: List[str] = []
    for level, current in enumerate([path, *path.parents]):
        if level > max_levels:
            break
        out.append(str(current))
        if root and os.path.normcase(os.path.normpath(str(current))) == root:
            break
    return out


def discover_kmls(folder: str, *, verify: bool = True, max_levels: int = 3) -> List[KmlProfile]:
    """Profile every KML found around ``folder``."""
    seen = set()
    profiles: List[KmlProfile] = []
    for directory in candidate_directories(folder, max_levels=max_levels):
        for path in _kml_files_in(directory):
            key = os.path.normcase(os.path.normpath(path))
            if key in seen:
                continue
            seen.add(key)
            profiles.append(profile_kml(path, verify=verify))
    return profiles


def _trace_rank(p: KmlProfile):
    """Best trace first: verified, then fuller, then most recently edited."""
    return (
        0 if p.trace_verified else 1,
        -p.pk_posts,
        -p.modified,
    )


def recommend(profiles: Iterable[KmlProfile]) -> KmlRecommendation:
    """Pick the trace and the landmark files out of a set of candidates."""
    traces: List[KmlProfile] = []
    result = KmlRecommendation()
    for p in profiles:
        if p.role == ROLE_TRACE:
            traces.append(p)
        elif p.role == ROLE_LANDMARKS:
            result.landmark_kmls.append(p)
        else:
            result.ignored.append(p)
    traces.sort(key=_trace_rank)
    if traces:
        result.trace = traces[0]
        result.alternatives = traces[1:]
    return result


def suggest_trace_for(kml_path: str, *, verify: bool = True) -> Optional[KmlProfile]:
    """The trace KML near ``kml_path`` if it is a different file, else None.

    Used when the chosen KML turns out not to be a trace, so the warning can
    say which file probably was meant.
    """
    if not kml_path:
        return None
    here = os.path.normcase(os.path.normpath(kml_path))
    best = recommend(discover_kmls(os.path.dirname(kml_path), verify=verify)).trace
    if best and os.path.normcase(os.path.normpath(best.path)) != here:
        return best
    return None


def unregistered_landmarks(trace: KmlProfile, registered: Iterable[str]) -> List[str]:
    """Landmarks the trace KML defines that the job has not registered.

    Torre Pacheco's trace KML carries Caliche, Palomares, Gregal and two
    Vertedero points in its own "Vertederos" folder, and the project holds a
    hand-typed copy of those names. Anything the KML defines and the project
    does not know about is a landfill whose photos are not routed to its
    folder, with nothing saying so.
    """
    known = {str(n).strip().casefold() for n in registered}
    return [n for n in trace.landmark_names if n.strip().casefold() not in known]


def describe(recommendation: KmlRecommendation, *, base: Sequence[str] = ()) -> str:
    """Human summary of a recommendation, for the log and the detection dialog."""
    lines: List[str] = []
    if recommendation.trace:
        t = recommendation.trace
        lines.append(f"Traza: {t.name} — {t.summary()}")
        for alt in recommendation.alternatives:
            lines.append(f"   (equivalente: {alt.name} — {alt.summary()})")
    else:
        lines.append("Traza: no se ha encontrado ningún KML con puntos de PK.")
    for lm in recommendation.landmark_kmls:
        lines.append(f"Vertederos: {lm.name} — {lm.summary()}")
    for ig in recommendation.ignored:
        lines.append(f"Ignorado: {ig.name} — {ig.summary()}")
    return "\n".join(lines)
