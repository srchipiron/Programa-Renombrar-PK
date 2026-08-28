"""
One-shot: rename July Torre Pacheco photos in place (no moves).

1) VERTEDEROS/<carpeta> -> <carpeta>_01.jpg, _02.jpg, ...
2) VIADUCTOS + raíz -> PK from GPS, stay in same folder.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager  # noqa: E402
from src.core.models import PhotoItem  # noqa: E402
from src.core.orientation import classify_view  # noqa: E402
from src.core.renamer_logic import RenamerLogic, find_sidecars  # noqa: E402
from src.core.spatial_calculator import SpatialCalculator  # noqa: E402

IMG_EXT = {".jpg", ".jpeg"}


def list_imgs(folder: str) -> List[str]:
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return [
        os.path.join(folder, name)
        for name in names
        if os.path.splitext(name)[1].lower() in IMG_EXT
    ]


def sort_key_seq(path: str) -> Tuple[int, str]:
    name = os.path.basename(path)
    # Traza … Julio 26-131.jpg
    m = re.search(r"(?:Julio|Junio)\s*26[-_]?(\d+)\.(?:jpg|jpeg)$", name, re.I)
    if m:
        return (int(m.group(1)), name.casefold())
    m = re.search(r"_(\d+)\.(?:jpg|jpeg)$", name, re.I)
    if m:
        return (int(m.group(1)), name.casefold())
    # Non-sequence names last
    return (10**9, name.casefold())


def two_phase_rename(pairs: List[Tuple[str, str]], dry: bool) -> List[Tuple[str, str]]:
    pairs = [
        (s, d)
        for s, d in pairs
        if os.path.normcase(os.path.abspath(s)) != os.path.normcase(os.path.abspath(d))
    ]
    if not pairs:
        return []

    dest_set = set()
    for src, dst in pairs:
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        key = os.path.normcase(os.path.abspath(dst))
        if key in dest_set:
            raise FileExistsError(f"Duplicate destination: {dst}")
        dest_set.add(key)

    sources = {os.path.normcase(os.path.abspath(s)) for s, _ in pairs}
    for _src, dst in pairs:
        dkey = os.path.normcase(os.path.abspath(dst))
        if os.path.exists(dst) and dkey not in sources:
            raise FileExistsError(f"Destination exists: {dst}")

    if dry:
        return pairs

    temps: List[Tuple[str, str, str]] = []
    for i, (src, dst) in enumerate(pairs):
        tmp = src + f".__tmp_ren_{i:04d}__"
        os.rename(src, tmp)
        temps.append((src, tmp, dst))

    applied: List[Tuple[str, str]] = []
    for src, tmp, dst in temps:
        if os.path.exists(dst):
            raise FileExistsError(dst)
        os.rename(tmp, dst)
        applied.append((src, dst))
    return applied


def plan_vertederos(base: str) -> List[Tuple[str, str]]:
    vert_root = os.path.join(base, "VERTEDEROS")
    plan: List[Tuple[str, str]] = []
    if not os.path.isdir(vert_root):
        return plan
    for sub in sorted(os.listdir(vert_root)):
        subdir = os.path.join(vert_root, sub)
        if not os.path.isdir(subdir):
            continue
        files = list_imgs(subdir)
        files.sort(key=sort_key_seq)
        for i, src in enumerate(files, 1):
            plan.append((src, os.path.join(subdir, f"{sub}_{i:02d}.jpg")))
    return plan


def setup_logic(cfg, kml: str) -> RenamerLogic:
    calc = SpatialCalculator()
    calc.load_kml(kml)
    if cfg.extra_landmarks:
        calc.add_landmarks_from_dicts(cfg.extra_landmarks)
    if cfg.landmark_groups:
        calc.set_landmark_groups(cfg.landmark_groups)
    calc.set_landmark_capture_radius(cfg.landmark_capture_radius)
    calc.set_landmark_cluster_params(
        cluster_radius_m=cfg.landmark_cluster_radius,
        split_ratio=cfg.landmark_split_ratio,
    )
    logic = RenamerLogic(calc, max_workers=cfg.max_workers or 4)
    if cfg.viaduct_pks:
        logic.set_viaduct_pks(cfg.viaduct_pks)
    return logic


def nearest_pk_ignoring_landmarks(calc: SpatialCalculator, lat: float, lon: float) -> Tuple[Optional[str], float]:
    """Nearest named PK point, skipping landmark placemarks."""
    from shapely.geometry import Point

    if not calc.named_points or not calc._points_metric:
        return None, float("inf")
    p = Point(calc._to_metric(lon, lat))
    best_name: Optional[str] = None
    best_dist = float("inf")
    for name, pt in zip(calc._points_names, calc._points_metric):
        if calc.is_landmark_name(name):
            continue
        d = float(pt.distance(p))
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name, best_dist


def analyze_flat_folder(logic: RenamerLogic, folder: str) -> List[PhotoItem]:
    files = list_imgs(folder)
    if not files:
        return []

    items: List[PhotoItem] = []
    calc = logic.spatial_calc

    def one(path: str) -> Optional[PhotoItem]:
        exif = logic._get_full_exif(path)
        if not exif:
            return None
        lat = exif["lat"]
        lon = exif["lon"]
        nearest_name, nearest_dist = nearest_pk_ignoring_landmarks(calc, lat, lon)
        dist_to_use = nearest_dist if nearest_name else float("inf")
        if not nearest_name and calc.project_axis is not None:
            dist_to_use = calc.distance_to_axis(lat, lon)
        pk_val = calc.calculate_pk(lat, lon)
        axis_bearing = calc.axis_bearing_at(lat, lon)
        view_label = classify_view(
            gimbal_yaw=exif.get("gimbal_yaw"),
            gimbal_pitch=exif.get("gimbal_pitch"),
            axis_bearing=axis_bearing,
        )
        return PhotoItem(
            path=path,
            name=os.path.basename(path),
            lat=lat,
            lon=lon,
            date_str=exif.get("date", ""),
            time_str=exif.get("time", ""),
            nearest_name=nearest_name,
            nearest_dist=nearest_dist,
            distance=dist_to_use,
            pk_value=pk_val,
            camera=exif.get("camera", ""),
            gimbal_yaw=exif.get("gimbal_yaw"),
            gimbal_pitch=exif.get("gimbal_pitch"),
            flight_yaw=exif.get("flight_yaw"),
            view_label=view_label,
            sidecars=find_sidecars(path),
        )

    total = len(files)
    done = 0
    with ThreadPoolExecutor(max_workers=logic.max_workers) as pool:
        futs = {pool.submit(one, p): p for p in files}
        for fut in as_completed(futs):
            done += 1
            if done == total or done % 30 == 0:
                print(f"  analyze {done}/{total}")
            try:
                item = fut.result()
            except Exception as exc:
                print(f"  FAIL {futs[fut]}: {exc}")
                continue
            if item:
                items.append(item)
    return items


def plan_pk_folder(
    folder: str,
    logic: RenamerLogic,
    threshold: float,
    suffix: str,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    items = analyze_flat_folder(logic, folder)
    skipped: List[str] = []
    named: List[PhotoItem] = []

    for img in items:
        clean = ""
        if img.nearest_name:
            clean = (
                logic.sanitize_pk_name(img.nearest_name)
                .upper()
                .replace("PK", "")
                .strip()
                .lstrip("-+")
                .strip()
            )
        if not clean or not re.search(r"\d+\+\d+", clean):
            if img.pk_value and img.pk_value > 0:
                km = int(img.pk_value // 1000)
                m = int(img.pk_value % 1000)
                clean = f"{km}+{m:03d}"
            else:
                skipped.append(f"{img.name}: sin PK (dist={img.distance:.1f})")
                continue
        if img.distance > threshold * 2:
            # Soft warn but still rename — user asked to fix names in place.
            print(f"  WARN far {img.name}: {img.distance:.1f}m -> PK-{clean}")
        img.new_name_base = f"PK-{clean}-{suffix}"
        img.is_inside_threshold = True
        named.append(img)

    groups: Dict[str, List[PhotoItem]] = defaultdict(list)
    for img in named:
        groups[img.new_name_base].append(img)

    plan: List[Tuple[str, str]] = []
    for base_name, group in groups.items():
        group.sort(key=lambda x: (x.date_str or "", x.time_str or "", x.name.casefold()))
        multiple = len(group) > 1
        for seq, img in enumerate(group, start=1):
            new_name = f"{base_name}_{seq:02d}.jpg" if multiple else f"{base_name}.jpg"
            plan.append((img.path, os.path.join(folder, new_name)))
    return plan, skipped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", choices=["all", "vertederos", "pk"], default="all")
    args = ap.parse_args()
    dry = not args.apply

    cfg = ConfigManager().config
    base = cfg.last_folder
    kml = cfg.last_kml
    suffix = "JUL26"
    threshold = float(cfg.threshold)

    print(f"BASE={base}")
    print(f"DRY={dry} only={args.only} threshold={threshold}")

    all_plans: List[Tuple[str, str]] = []

    if args.only in ("all", "vertederos"):
        vplan = plan_vertederos(base)
        changed = [(s, d) for s, d in vplan if os.path.normcase(s) != os.path.normcase(d)]
        print(f"\n=== VERTEDEROS ({len(changed)} renames) ===")
        for s, d in changed:
            print(f"  {os.path.relpath(s, base)} -> {os.path.basename(d)}")
        all_plans.extend(changed)

    if args.only in ("all", "pk"):
        logic = setup_logic(cfg, kml)
        for label, folder in (
            ("VIADUCTOS", os.path.join(base, "VIADUCTOS")),
            ("RAIZ", base),
        ):
            print(f"\n=== Analyzing {label} ===")
            plan, skipped = plan_pk_folder(folder, logic, threshold=threshold, suffix=suffix)
            changed = [(s, d) for s, d in plan if os.path.normcase(s) != os.path.normcase(d)]
            keep = len(plan) - len(changed)
            print(
                f"=== {label}: {len(changed)} renames, {keep} already ok, "
                f"{len(skipped)} skipped ==="
            )
            for s, d in changed[:50]:
                print(f"  {os.path.basename(s)} -> {os.path.basename(d)}")
            if len(changed) > 50:
                print(f"  ... +{len(changed) - 50} more")
            for line in skipped[:20]:
                print(f"  SKIP {line}")
            all_plans.extend(changed)

    print(f"\nTOTAL renames: {len(all_plans)}")
    if dry:
        print("Dry-run only. Re-run with --apply to execute.")
        return 0

    by_dir: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for s, d in all_plans:
        by_dir[os.path.dirname(s)].append((s, d))

    for folder, pairs in by_dir.items():
        print(f"Applying in {folder} ({len(pairs)})...")
        two_phase_rename(pairs, dry=False)

    report = ROOT / "logs" / "rename_julio_inplace_report.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(
        json.dumps([{"src": s, "dst": d} for s, d in all_plans], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Done. Report: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
