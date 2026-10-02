"""Export analyzed photos + coverage gaps as GeoJSON for GIS handoff.

Produces a FeatureCollection (WGS84) with:
- Point features for each analyzed photo (calibrated chainage, distance, rename plan)
- Optional LineString features for coverage gaps projected onto the project axis
  (interior holes plus the un-flown head/tail of the trace)
- Point features for PK placemarks that never got a photo
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .coverage import GAP_INTERIOR, CoverageReport, compute_coverage
from .models import PhotoItem
from .spatial_calculator import METERS_PER_DEGREE, SpatialCalculator


def _photo_feature(item: PhotoItem) -> Dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Point",
            "coordinates": [float(item.lon), float(item.lat)],
        },
        "properties": {
            "original": item.name,
            "path": item.path,
            "new_name": item.new_name_base or "",
            "pk_nearest": item.nearest_name or "",
            "pk_chainage": SpatialCalculator.format_pk_label(item.pk_value),
            "pk_value_m": round(float(item.pk_value), 3),
            "distance_m": (
                None if item.distance == float("inf") else round(float(item.distance), 3)
            ),
            "inside_threshold": bool(item.is_inside_threshold),
            "excluded": bool(item.excluded),
            "view": item.view_label or "",
            "date": item.date_str or "",
            "time": item.time_str or "",
            "camera": item.camera or "",
            "duplicate_of": item.duplicate_of or "",
            "feature_kind": "photo",
        },
    }


def _geom_dist_for_official_pk(calc: SpatialCalculator, official_pk: float) -> Optional[float]:
    """Inverse of calibrated chainage: official PK metres → axis arc-length."""
    cal = list(getattr(calc, "_pk_calibration", None) or [])
    if len(cal) >= 2:
        # Ensure anchors are ordered by official PK for inverse lookup.
        by_pk = sorted(cal, key=lambda pair: pair[1])
        if official_pk <= by_pk[0][1]:
            g0, p0 = by_pk[0]
            g1, p1 = by_pk[1]
            span = p1 - p0
            if abs(span) < 1e-9:
                return g0
            return g0 + (official_pk - p0) * (g1 - g0) / span
        if official_pk >= by_pk[-1][1]:
            g0, p0 = by_pk[-2]
            g1, p1 = by_pk[-1]
            span = p1 - p0
            if abs(span) < 1e-9:
                return g1
            return g0 + (official_pk - p0) * (g1 - g0) / span
        for i in range(len(by_pk) - 1):
            g0, p0 = by_pk[i]
            g1, p1 = by_pk[i + 1]
            lo, hi = (p0, p1) if p0 <= p1 else (p1, p0)
            if lo <= official_pk <= hi:
                span = p1 - p0
                if abs(span) < 1e-9:
                    return g0
                t = (official_pk - p0) / span
                return g0 + t * (g1 - g0)
    if calc._axis_metric is None:
        return None
    return float(official_pk) - float(calc.pk_offset)


def _wgs84_point_at_geom(calc: SpatialCalculator, geom_dist: float) -> Optional[List[float]]:
    """Return ``[lon, lat]`` for a metric distance along the project axis."""
    if calc._axis_metric is None:
        return None
    clamped = max(0.0, min(float(geom_dist), float(calc._axis_metric.length)))
    pt = calc._axis_metric.interpolate(clamped)
    lon_scale = METERS_PER_DEGREE * calc._lon_scale
    if abs(lon_scale) < 1e-12:
        return None
    lon = (pt.x / lon_scale) + calc._lon0
    lat = (pt.y / METERS_PER_DEGREE) + calc._lat0
    return [lon, lat]


def _gap_feature_on_axis(
    calc: SpatialCalculator,
    gap_start: float,
    gap_end: float,
    *,
    seq: int,
    kind: str = GAP_INTERIOR,
) -> Optional[Dict[str, Any]]:
    """Project a coverage gap onto the real centreline as a WGS84 LineString."""
    g0 = _geom_dist_for_official_pk(calc, gap_start)
    g1 = _geom_dist_for_official_pk(calc, gap_end)
    if g0 is None or g1 is None or calc._axis_metric is None:
        return None
    samples = 8
    coords: List[List[float]] = []
    for i in range(samples + 1):
        t = i / samples
        gd = g0 + t * (g1 - g0)
        pt = _wgs84_point_at_geom(calc, gd)
        if pt is not None:
            coords.append(pt)
    if len(coords) < 2:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "feature_kind": "coverage_gap",
            "gap_kind": kind,
            "pk_start": SpatialCalculator.format_pk_label(gap_start),
            "pk_end": SpatialCalculator.format_pk_label(gap_end),
            "pk_start_m": round(gap_start, 3),
            "pk_end_m": round(gap_end, 3),
            "length_m": round(gap_end - gap_start, 3),
            "gap_index": seq,
        },
    }


def _missing_pk_features(
    calc: SpatialCalculator,
    coverage: CoverageReport,
) -> List[Dict[str, Any]]:
    """Point features for PK placemarks with no photo within tolerance."""
    if not coverage.missing_pks:
        return []
    by_name = {pt.name: pt for pt in calc.named_points}
    features: List[Dict[str, Any]] = []
    for missing in coverage.missing_pks:
        pt = by_name.get(missing.name)
        if pt is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(pt.lon), float(pt.lat)],
                },
                "properties": {
                    "feature_kind": "missing_pk",
                    "name": missing.name,
                    "pk": SpatialCalculator.format_pk_label(missing.pk_m),
                    "pk_value_m": round(float(missing.pk_m), 3),
                    "tolerance_m": coverage.pk_tolerance_m,
                },
            }
        )
    return features


def build_analysis_geojson(
    items: Sequence[PhotoItem],
    *,
    coverage: Optional[CoverageReport] = None,
    gap_min_m: Optional[float] = None,
    include_outside: bool = True,
    include_gaps: bool = True,
    spatial_calc: Optional[SpatialCalculator] = None,
) -> Dict[str, Any]:
    """Build a GeoJSON FeatureCollection from analyzed photos."""
    if coverage is None:
        coverage = compute_coverage(
            items, gap_min_m=gap_min_m, spatial_calc=spatial_calc
        )

    features: List[Dict[str, Any]] = []
    for item in items:
        if not include_outside and not item.is_inside_threshold and not item.excluded:
            continue
        features.append(_photo_feature(item))

    if include_gaps and spatial_calc is not None and spatial_calc.project_axis is not None:
        for idx, gap in enumerate(coverage.gaps, start=1):
            feat = _gap_feature_on_axis(
                spatial_calc,
                gap.start_pk_m,
                gap.end_pk_m,
                seq=idx,
                kind=gap.kind,
            )
            if feat is not None:
                features.append(feat)

    if spatial_calc is not None:
        features.extend(_missing_pk_features(spatial_calc, coverage))

    return {
        "type": "FeatureCollection",
        "name": "renombrador_pks_analisis",
        "features": features,
        "properties": {
            "inside_count": coverage.inside_count,
            "outside_count": coverage.outside_count,
            "excluded_count": coverage.excluded_count,
            "gap_count": coverage.gap_count,
            "pk_min": (
                SpatialCalculator.format_pk_label(coverage.pk_min_m)
                if coverage.pk_min_m is not None
                else None
            ),
            "pk_max": (
                SpatialCalculator.format_pk_label(coverage.pk_max_m)
                if coverage.pk_max_m is not None
                else None
            ),
            "gap_min_m": coverage.gap_min_m,
            "trace_pk_min": (
                SpatialCalculator.format_pk_label(coverage.trace_start_pk_m)
                if coverage.trace_start_pk_m is not None
                else None
            ),
            "trace_pk_max": (
                SpatialCalculator.format_pk_label(coverage.trace_end_pk_m)
                if coverage.trace_end_pk_m is not None
                else None
            ),
            "trace_length_m": round(coverage.trace_length_m, 3),
            "covered_m": round(coverage.covered_m, 3),
            "coverage_ratio": (
                round(coverage.coverage_ratio, 4)
                if coverage.coverage_ratio is not None
                else None
            ),
            "pk_total": coverage.pk_total,
            "pk_missing": len(coverage.missing_pks),
            "pk_tolerance_m": coverage.pk_tolerance_m,
        },
    }


def export_analysis_geojson(
    items: Sequence[PhotoItem],
    path: Union[str, Path],
    *,
    gap_min_m: Optional[float] = None,
    include_outside: bool = True,
    include_gaps: bool = True,
    spatial_calc: Optional[SpatialCalculator] = None,
) -> CoverageReport:
    """Write the GeoJSON file and return the coverage report used."""
    coverage = compute_coverage(
        items, gap_min_m=gap_min_m, spatial_calc=spatial_calc
    )
    payload = build_analysis_geojson(
        items,
        coverage=coverage,
        gap_min_m=gap_min_m,
        include_outside=include_outside,
        include_gaps=include_gaps,
        spatial_calc=spatial_calc,
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return coverage
