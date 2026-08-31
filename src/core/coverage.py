"""Corridor coverage QA — detect chainage gaps after analysis.

After a flight, operators need a fast answer to: "did we cover the whole
trace, or are there silent holes along the PK?". This module is pure and
UI-free so it can be unit-tested and reused from workers or export paths.

Coverage is measured against the **trace**, not only against the photos:
gaps between consecutive photos (interior), plus the stretches before the
first and after the last photo (head / tail). A survey that skipped the first
two kilometres has no interior gap at all, yet is two kilometres short — which
is exactly the failure worth catching before leaving the site.
"""
from __future__ import annotations

import statistics
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence, Tuple

from .models import PhotoItem
from .spatial_calculator import SpatialCalculator

#: Default radius (m) within which a photo counts as covering a PK placemark
#: — and, symmetrically, the stretch of trace one photo is credited with.
DEFAULT_PK_TOLERANCE_M = 50.0

#: A hole is only worth reporting when it is this many times the flight's own
#: median photo spacing. Corridor flights shoot every 100–200 m, so a fixed
#: 100 m threshold flags *every* interval; scaling to the observed cadence
#: flags only where the drone actually skipped something.
GAP_SPACING_MULTIPLIER = 2.5

#: Never report holes shorter than this, however dense the flight was.
GAP_MIN_FLOOR_M = 100.0

#: Photos closer together than this are a burst at one spot (TI/CEN/TD of the
#: same PK), not cadence — excluded from the spacing median.
_BURST_SPACING_M = 5.0


def suggest_gap_min(
    samples: Sequence[float],
    *,
    floor_m: float = GAP_MIN_FLOOR_M,
    multiplier: float = GAP_SPACING_MULTIPLIER,
) -> float:
    """Gap threshold scaled to the flight's own photo cadence.

    ``samples`` are chainage values in metres (sorted or not). Returns
    ``floor_m`` when there is not enough evidence to infer a cadence.
    """
    ordered = sorted(float(v) for v in samples)
    deltas = [
        b - a
        for a, b in zip(ordered, ordered[1:])
        if b - a >= _BURST_SPACING_M
    ]
    if len(deltas) < 3:
        return float(floor_m)
    return max(float(floor_m), float(multiplier) * statistics.median(deltas))


GAP_INTERIOR = "interior"
GAP_HEAD = "inicio"
GAP_TAIL = "final"

_GAP_KIND_LABEL = {
    GAP_HEAD: "inicio de traza",
    GAP_TAIL: "final de traza",
}


@dataclass(frozen=True)
class CoverageGap:
    """A stretch of official chainage with no photos inside the threshold."""

    start_pk_m: float
    end_pk_m: float
    #: ``interior`` (between two photos), ``inicio`` (trace start → first
    #: photo) or ``final`` (last photo → trace end).
    kind: str = GAP_INTERIOR

    @property
    def length_m(self) -> float:
        return max(0.0, self.end_pk_m - self.start_pk_m)

    @property
    def label(self) -> str:
        start = SpatialCalculator.format_pk_label(self.start_pk_m)
        end = SpatialCalculator.format_pk_label(self.end_pk_m)
        base = f"PK-{start} → PK-{end} ({self.length_m:.0f} m)"
        extra = _GAP_KIND_LABEL.get(self.kind)
        return f"{base} [{extra}]" if extra else base


@dataclass(frozen=True)
class MissingPk:
    """A PK placemark of the KML with no photo within tolerance."""

    name: str
    pk_m: float

    @property
    def label(self) -> str:
        return f"PK-{SpatialCalculator.format_pk_label(self.pk_m)}"


@dataclass
class CoverageReport:
    """Summary of chainage coverage for the photos inside the threshold."""

    inside_count: int = 0
    outside_count: int = 0
    excluded_count: int = 0
    pk_min_m: Optional[float] = None
    pk_max_m: Optional[float] = None
    span_m: float = 0.0
    gaps: List[CoverageGap] = field(default_factory=list)
    gap_min_m: float = GAP_MIN_FLOOR_M
    #: True when ``gap_min_m`` was derived from the flight's own cadence.
    gap_min_auto: bool = False

    # --- Trace-relative QA (only filled when the trace extent is known) ---
    #: Official chainage span of the loaded trace.
    trace_start_pk_m: Optional[float] = None
    trace_end_pk_m: Optional[float] = None
    #: Metres of trace with photo evidence, and the same as a 0..1 ratio.
    covered_m: float = 0.0
    coverage_ratio: Optional[float] = None
    #: PK placemarks of the KML with no photo within ``pk_tolerance_m``.
    missing_pks: List[MissingPk] = field(default_factory=list)
    pk_tolerance_m: float = DEFAULT_PK_TOLERANCE_M
    #: Total PK placemarks considered (denominator of ``missing_pks``).
    pk_total: int = 0

    @property
    def gap_count(self) -> int:
        return len(self.gaps)

    @property
    def interior_gaps(self) -> List[CoverageGap]:
        return [g for g in self.gaps if g.kind == GAP_INTERIOR]

    @property
    def largest_gap_m(self) -> float:
        if not self.gaps:
            return 0.0
        return max(g.length_m for g in self.gaps)

    @property
    def trace_length_m(self) -> float:
        if self.trace_start_pk_m is None or self.trace_end_pk_m is None:
            return 0.0
        return max(0.0, self.trace_end_pk_m - self.trace_start_pk_m)

    @property
    def covered_pk_count(self) -> int:
        return max(0, self.pk_total - len(self.missing_pks))

    def trace_line(self) -> str:
        """One-liner describing coverage of the trace, or ``""`` if unknown.

        "Coverage" is the share of the trace lying within ``pk_tolerance_m`` of
        some photo — not the share of chainage between photos, which would read
        ~0 % for any flight that shoots every 150 m.
        """
        if self.coverage_ratio is None:
            return ""
        lo = SpatialCalculator.format_pk_label(self.trace_start_pk_m or 0.0)
        hi = SpatialCalculator.format_pk_label(self.trace_end_pk_m or 0.0)
        text = f"{self.coverage_ratio * 100:.0f}% de la traza (PK-{lo}–PK-{hi})"
        if self.pk_total:
            text += f" · {self.covered_pk_count}/{self.pk_total} PK con foto"
        return text

    def status_line(self, *, max_gaps: int = 2) -> str:
        """Compact one-liner for the status bar / log."""
        if self.inside_count == 0 or self.pk_min_m is None or self.pk_max_m is None:
            return "Cobertura: sin fotos dentro del umbral"

        lo = SpatialCalculator.format_pk_label(self.pk_min_m)
        hi = SpatialCalculator.format_pk_label(self.pk_max_m)
        parts = [
            f"Cobertura PK-{lo}–PK-{hi}",
            f"{self.inside_count} dentro",
        ]
        trace = self.trace_line()
        if trace:
            parts.append(trace)
        if self.gap_count == 0:
            parts.append("sin huecos")
        else:
            auto = " auto" if self.gap_min_auto else ""
            parts.append(f"{self.gap_count} hueco(s) ≥{self.gap_min_m:.0f} m{auto}")
            shown = self.gaps[:max_gaps]
            parts.append("; ".join(g.label for g in shown))
            if self.gap_count > max_gaps:
                parts.append(f"+{self.gap_count - max_gaps} más")
        return " · ".join(parts)


def _resolve_trace_extent(
    spatial_calc: Optional[SpatialCalculator],
    trace_extent: Optional[Tuple[float, float]],
) -> Optional[Tuple[float, float]]:
    if trace_extent is not None:
        lo, hi = float(trace_extent[0]), float(trace_extent[1])
        if hi < lo:
            lo, hi = hi, lo
        return (lo, hi) if hi > lo else None
    if spatial_calc is None:
        return None
    try:
        return spatial_calc.axis_pk_extent()
    except Exception:  # pragma: no cover - defensive: never break analysis QA
        return None


def _missing_placemarks(
    spatial_calc: Optional[SpatialCalculator],
    samples: Sequence[float],
    tolerance_m: float,
) -> Tuple[List[MissingPk], int]:
    """PK placemarks with no photo within ``tolerance_m`` (binary search)."""
    if spatial_calc is None:
        return [], 0
    try:
        placemarks = spatial_calc.pk_placemarks()
    except Exception:  # pragma: no cover - defensive
        return [], 0
    if not placemarks:
        return [], 0
    missing: List[MissingPk] = []
    for name, pk in placemarks:
        idx = bisect_left(samples, pk)
        nearest = float("inf")
        if idx < len(samples):
            nearest = min(nearest, samples[idx] - pk)
        if idx > 0:
            nearest = min(nearest, pk - samples[idx - 1])
        if nearest > tolerance_m:
            missing.append(MissingPk(name=name, pk_m=pk))
    return missing, len(placemarks)


def _covered_metres(
    samples: Sequence[float],
    extent: Tuple[float, float],
    tolerance_m: float,
) -> float:
    """Metres of trace within ``tolerance_m`` of at least one photo.

    Crediting each photo with only its own point would report ~0 % coverage for
    any real corridor flight (one shot every 100–200 m), which tells the
    operator nothing. Each photo covers ``±tolerance_m`` instead — the same
    radius used to decide whether a PK placemark got photographed — and the
    intervals are merged so overlapping bursts are not counted twice.
    """
    trace_lo, trace_hi = extent
    radius = max(0.0, float(tolerance_m))
    covered = 0.0
    cur_lo: Optional[float] = None
    cur_hi = 0.0
    for pk in samples:  # already sorted by the caller
        lo = max(trace_lo, pk - radius)
        hi = min(trace_hi, pk + radius)
        if hi <= lo:
            continue
        if cur_lo is None:
            cur_lo, cur_hi = lo, hi
        elif lo <= cur_hi:
            cur_hi = max(cur_hi, hi)
        else:
            covered += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
    if cur_lo is not None:
        covered += cur_hi - cur_lo
    return covered


def compute_coverage(
    items: Sequence[PhotoItem],
    *,
    gap_min_m: Optional[float] = None,
    only_inside: bool = True,
    spatial_calc: Optional[SpatialCalculator] = None,
    trace_extent: Optional[Tuple[float, float]] = None,
    pk_tolerance_m: float = DEFAULT_PK_TOLERANCE_M,
) -> CoverageReport:
    """Detect gaps between consecutive photos ordered by calibrated PK.

    Photos must already carry ``pk_value`` from analysis. By default only
    items inside the threshold and not excluded are treated as coverage
    evidence (outliers off-corridor should not "fill" a gap).

    ``gap_min_m`` defaults to :func:`suggest_gap_min` — the flight's own median
    spacing times :data:`GAP_SPACING_MULTIPLIER`, floored at
    :data:`GAP_MIN_FLOOR_M`. Pass a number to pin it.

    Pass ``spatial_calc`` (or an explicit ``trace_extent``) to also measure
    coverage against the trace itself: head/tail gaps, a coverage ratio and
    the PK placemarks that never got a photo.
    """
    tolerance = max(0.0, float(pk_tolerance_m))
    inside = 0
    outside = 0
    excluded = 0
    samples: List[float] = []

    for item in items:
        if item.excluded:
            excluded += 1
            continue
        if item.is_inside_threshold:
            inside += 1
            if only_inside and item.pk_value is not None:
                samples.append(float(item.pk_value))
        else:
            outside += 1
            if not only_inside and item.pk_value is not None:
                samples.append(float(item.pk_value))

    samples.sort()
    gap_auto = gap_min_m is None
    gap_min = max(1.0, suggest_gap_min(samples) if gap_auto else float(gap_min_m))

    report = CoverageReport(
        inside_count=inside,
        outside_count=outside,
        excluded_count=excluded,
        gap_min_m=gap_min,
        gap_min_auto=gap_auto,
        pk_tolerance_m=tolerance,
    )

    extent = _resolve_trace_extent(spatial_calc, trace_extent)
    if extent is not None:
        report.trace_start_pk_m, report.trace_end_pk_m = extent

    if samples:
        report.pk_min_m = samples[0]
        report.pk_max_m = samples[-1]
        report.span_m = samples[-1] - samples[0]

    gaps: List[CoverageGap] = []
    for prev, nxt in zip(samples, samples[1:]):
        if nxt - prev >= gap_min:
            gaps.append(CoverageGap(start_pk_m=prev, end_pk_m=nxt, kind=GAP_INTERIOR))

    if extent is not None:
        trace_lo, trace_hi = extent
        if samples:
            if samples[0] - trace_lo >= gap_min:
                gaps.insert(
                    0,
                    CoverageGap(start_pk_m=trace_lo, end_pk_m=samples[0], kind=GAP_HEAD),
                )
            if trace_hi - samples[-1] >= gap_min:
                gaps.append(
                    CoverageGap(start_pk_m=samples[-1], end_pk_m=trace_hi, kind=GAP_TAIL)
                )
        else:
            # Nothing surveyed at all: the whole trace is one gap.
            gaps.append(
                CoverageGap(start_pk_m=trace_lo, end_pk_m=trace_hi, kind=GAP_HEAD)
            )

    gaps.sort(key=lambda g: (g.start_pk_m, g.end_pk_m))
    report.gaps = gaps

    if extent is not None:
        trace_lo, trace_hi = extent
        trace_len = trace_hi - trace_lo
        report.covered_m = _covered_metres(samples, extent, tolerance)
        report.coverage_ratio = (
            max(0.0, min(1.0, report.covered_m / trace_len)) if trace_len > 0 else None
        )

    report.missing_pks, report.pk_total = _missing_placemarks(
        spatial_calc, samples, tolerance
    )
    return report


def coverage_from_distances(
    pk_values: Iterable[float],
    *,
    gap_min_m: Optional[float] = GAP_MIN_FLOOR_M,
    trace_extent: Optional[Tuple[float, float]] = None,
) -> CoverageReport:
    """Convenience for tests / scripts that only have a list of PK metres."""
    items = [
        PhotoItem(
            path=f"virtual_{i}.jpg",
            name=f"virtual_{i}.jpg",
            lat=0.0,
            lon=0.0,
            pk_value=float(pk),
            is_inside_threshold=True,
        )
        for i, pk in enumerate(pk_values)
    ]
    return compute_coverage(items, gap_min_m=gap_min_m, trace_extent=trace_extent)
