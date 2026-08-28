"""Benchmark the two O(n^2) hot spots removed from the analysis path.

1. **Sidecar discovery** — one ``os.scandir`` per photo (legacy) vs one listing
   per directory reused from the ``os.walk`` that analysis already performs.
2. **Nearest-PK lookup with landmarks configured** — a full scan of every named
   point per photo (legacy) vs the cached landmark/PK partition + PK STRtree.

Run:  set PYTHONPATH=. && python scripts/bench_analysis_hotpath.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shapely.geometry import Point  # noqa: E402

from src.core.models import KMLPoint  # noqa: E402
from src.core.renamer_logic import (  # noqa: E402
    SIDECAR_EXTENSIONS,
    collect_analysis_tree,
)
from src.core.spatial_calculator import SpatialCalculator  # noqa: E402


# --------------------------------------------------------------------------
# 1. Sidecar discovery
# --------------------------------------------------------------------------
def legacy_find_sidecars(photo_path: str) -> List[str]:
    """The pre-optimization implementation: one scandir per photo."""
    directory = os.path.dirname(photo_path)
    stem = os.path.splitext(os.path.basename(photo_path))[0]
    sidecars: List[str] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                entry_stem, entry_ext = os.path.splitext(entry.name)
                if entry_stem != stem or entry.path == photo_path:
                    continue
                if entry_ext.lower() in SIDECAR_EXTENSIONS:
                    sidecars.append(entry.path)
    except OSError:
        pass
    return sidecars


def _make_tree(n_photos: int, sidecar_ratio: float = 0.5) -> str:
    root = tempfile.mkdtemp(prefix="pk_hotpath_")
    for i in range(n_photos):
        open(os.path.join(root, f"DJI_{i:05d}.JPG"), "wb").close()
        if i % max(1, int(1 / sidecar_ratio)) == 0:
            open(os.path.join(root, f"DJI_{i:05d}.DNG"), "wb").close()
    return root


def bench_sidecars(sizes: Tuple[int, ...]) -> None:
    print("== Sidecar discovery (local SSD; network shares scale far worse) ==")
    print(f"{'photos':>7} {'legacy (s)':>12} {'indexed (s)':>12} {'speedup':>9}")
    for n in sizes:
        root = _make_tree(n)
        try:
            paths, index = collect_analysis_tree(root)
            assert len(paths) == n, (len(paths), n)

            t0 = time.perf_counter()
            legacy_total = sum(len(legacy_find_sidecars(p)) for p in paths)
            t_legacy = time.perf_counter() - t0

            t0 = time.perf_counter()
            _paths, index = collect_analysis_tree(root)
            new_total = sum(len(index.find(p)) for p in _paths)
            t_new = time.perf_counter() - t0

            assert legacy_total == new_total, (legacy_total, new_total)
            print(
                f"{n:>7} {t_legacy:>12.3f} {t_new:>12.3f} "
                f"{t_legacy / max(t_new, 1e-9):>8.1f}x"
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


# --------------------------------------------------------------------------
# 2. Nearest-PK with landmarks configured
# --------------------------------------------------------------------------
def _build_calc(n_points: int, n_landmarks: int) -> SpatialCalculator:
    calc = SpatialCalculator()
    lat0, lon0 = 37.80, -0.96
    calc.named_points = [
        KMLPoint(name=f"PK-{i // 10}+{(i % 10) * 100:03d}", lat=lat0 + i * 1e-4, lon=lon0)
        for i in range(n_points)
    ]
    calc.add_landmarks_from_dicts(
        [
            {"name": f"Vertedero {j}", "lat": lat0 + j * 5e-3, "lon": lon0 + 2e-3}
            for j in range(n_landmarks)
        ]
    )
    return calc


def legacy_nearest(calc: SpatialCalculator, lat: float, lon: float):
    """Pre-optimization lookup: linear sweeps over every named point."""
    p = Point(calc._to_metric(lon, lat))
    candidates = []
    for idx, name in enumerate(calc._points_names):
        if name.strip().casefold() not in calc._landmark_names:
            continue
        dist = float(calc._points_metric[idx].distance(p))
        if dist <= calc._landmark_capture_radius:
            pt = calc.named_points[idx]
            candidates.append((name, dist, pt.lat, pt.lon))
    if candidates:
        candidates.sort(key=lambda item: item[1])
        return candidates[0][0], candidates[0][1]
    idx = int(calc._points_tree.nearest(p))
    name = calc._points_names[idx]
    dist = float(calc._points_metric[idx].distance(p))
    if calc.is_landmark_name(name) and dist > calc._landmark_capture_radius:
        best_name, best_dist = None, float("inf")
        for i, n in enumerate(calc._points_names):
            if calc.is_landmark_name(n):
                continue
            d = float(calc._points_metric[i].distance(p))
            if d < best_dist:
                best_name, best_dist = n, d
        return best_name, best_dist
    return name, dist


def bench_nearest(n_points: int = 400, n_landmarks: int = 5, n_photos: int = 4000) -> None:
    print()
    print(f"== Nearest-PK lookup ({n_points} PK placemarks + {n_landmarks} landmarks) ==")
    calc = _build_calc(n_points, n_landmarks)
    lat0, lon0 = 37.80, -0.96
    coords = [(lat0 + (i % n_points) * 1e-4 + 2e-6, lon0 + 1e-5) for i in range(n_photos)]

    # warm both paths
    legacy_nearest(calc, *coords[0])
    calc.find_nearest_pk_name(*coords[0])

    t0 = time.perf_counter()
    legacy = [legacy_nearest(calc, la, lo) for la, lo in coords]
    t_legacy = time.perf_counter() - t0

    t0 = time.perf_counter()
    new = [calc.find_nearest_pk_name(la, lo) for la, lo in coords]
    t_new = time.perf_counter() - t0

    mismatches = sum(1 for a, b in zip(legacy, new) if a[0] != b[0])
    print(f"{'photos':>7} {'legacy (s)':>12} {'indexed (s)':>12} {'speedup':>9}")
    print(
        f"{n_photos:>7} {t_legacy:>12.3f} {t_new:>12.3f} "
        f"{t_legacy / max(t_new, 1e-9):>8.1f}x"
    )
    print(f"name mismatches vs legacy: {mismatches}")


def main() -> None:
    bench_sidecars((500, 1000, 2000))
    bench_nearest()


if __name__ == "__main__":
    main()
