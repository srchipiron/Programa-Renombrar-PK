"""Data models used across the application."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class KMLPoint:
    name: str
    lat: float
    lon: float


@dataclass
class PhotoItem:
    """A single analyzed photograph.

    The structural fields (``path``..``pk_value``) are populated by
    :class:`~src.core.renamer_logic.RenamerLogic` during analysis.  The
    "preview/UI" fields are filled later when building the rename plan and
    used by the UI layer.
    """

    path: str
    name: str
    lat: float
    lon: float
    date_str: str = ""
    time_str: str = ""
    nearest_name: Optional[str] = None
    nearest_dist: float = float("inf")
    distance: float = float("inf")
    pk_value: float = 0.0

    # --- Preview / UI state ---------------------------------------------
    new_name_base: str = ""
    pk_display: str = ""
    is_inside_threshold: bool = False

    #: When True the user has explicitly excluded this photo from the
    #: rename pipeline via the preview table.
    excluded: bool = False

    #: Populated when duplicate detection (same GPS + close timestamp) fires.
    duplicate_of: Optional[str] = None

    #: Companion files (RAW/DNG/XMP/...) found alongside the photo.
    sidecars: List[str] = field(default_factory=list)

    #: True for telemetry-derived frames (SRT video import): they carry a
    #: position and count as coverage evidence, but no file exists on disk,
    #: so they must never reach the rename plan. ``path`` is a synthetic
    #: ``<srt>#NNNNNN`` marker kept unique so preview rows stay distinct.
    virtual: bool = False

    # --- EXIF extras ----------------------------------------------------
    camera: str = ""
    gimbal_yaw: Optional[float] = None
    gimbal_pitch: Optional[float] = None
    gimbal_roll: Optional[float] = None
    flight_yaw: Optional[float] = None
    rel_altitude: Optional[float] = None
    #: CEN / TD / TI / TRAZA when orientation + axis bearing are known.
    view_label: str = ""

    #: Relative destination under the job folder (e.g. ``VIADUCTOS``,
    #: ``VERTEDEROS/Caliche``). Empty means the job root. Filled by the
    #: preview / rename-plan path so operators can audit routing before F7.
    dest_rel: str = ""
