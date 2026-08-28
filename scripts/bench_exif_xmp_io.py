"""Benchmark EXIF+XMP metadata extraction: dual-open (legacy) vs single-pass.

Measures the cold-analysis hot path that dominates F5 on network shares.

Run:  set PYTHONPATH=. && python scripts/bench_exif_xmp_io.py
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time

import piexif
from PIL import Image, ImageDraw

from src.core.orientation import inject_jpeg_xmp_packet, parse_dji_xmp
from src.core.renamer_logic import RenamerLogic
from src.core.spatial_calculator import SpatialCalculator


def _build_sample(path: str) -> None:
    gps = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: ((37, 1), (48, 1), (0, 1)),
        piexif.GPSIFD.GPSLongitudeRef: b"W",
        piexif.GPSIFD.GPSLongitude: ((0, 1), (58, 1), (0, 1)),
    }
    exif_dict = {
        "0th": {
            piexif.ImageIFD.Make: b"DJI",
            piexif.ImageIFD.Model: b"FC6310",
        },
        "Exif": {piexif.ExifIFD.DateTimeOriginal: b"2026:08:01 12:00:00"},
        "GPS": gps,
    }
    exif_bytes = piexif.dump(exif_dict)
    img = Image.new("RGB", (4000, 3000), color=(40, 80, 120))
    draw = ImageDraw.Draw(img)
    for i in range(0, 4000, 40):
        draw.line([(i, 0), (i, 3000)], fill=(i % 255, 100, 50))
    img.save(path, "JPEG", quality=92, exif=exif_bytes)

    xmp_body = (
        b'<x:xmpmeta xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/">'
        b'<rdf:Description drone-dji:GimbalYawDegree="+100.00" '
        b'drone-dji:GimbalPitchDegree="-30.00" '
        b'drone-dji:GimbalRollDegree="0.00" '
        b'drone-dji:FlightYawDegree="-169.20" '
        b'drone-dji:RelativeAltitude="+120.5"/>'
        b"</x:xmpmeta>"
    )
    overhead = b"http://ns.adobe.com/xap/1.0/\x00"
    payload = overhead + xmp_body
    xmp_seg = b"\xff\xe1" + (2 + len(payload)).to_bytes(2, "big") + payload
    if not inject_jpeg_xmp_packet(path, xmp_seg):
        raise RuntimeError("XMP inject failed")


def legacy_dual_open(path: str) -> None:
    """Pre-optimization path: Pillow EXIF open + separate 1 MiB XMP read."""
    with Image.open(path) as im:
        piexif.load(im.info.get("exif"))
    parse_dji_xmp(path)


def main() -> None:
    tmpdir = tempfile.mkdtemp(prefix="pk_exif_bench_")
    path = os.path.join(tmpdir, "dji.jpg")
    _build_sample(path)
    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"sample={path}")
    print(f"size={size_mb:.2f} MiB")

    renamer = RenamerLogic(SpatialCalculator())
    payload = renamer._get_full_exif(path)
    assert payload and payload.get("gimbal_yaw") == 100.0, payload
    print(f"payload_ok camera={payload.get('camera')!r} yaw={payload.get('gimbal_yaw')}")

    paths = []
    for i in range(60):
        p = os.path.join(tmpdir, f"dji_{i}.jpg")
        shutil.copy2(path, p)
        paths.append(p)

    # Warm filesystem / import caches once.
    legacy_dual_open(paths[0])
    renamer._get_full_exif(paths[0])

    t0 = time.perf_counter()
    for p in paths:
        legacy_dual_open(p)
    t_before = time.perf_counter() - t0

    t0 = time.perf_counter()
    for p in paths:
        renamer._get_full_exif(p)
    t_after = time.perf_counter() - t0

    n = len(paths)
    print(f"unique_files n={n}")
    print(f"  BEFORE dual-open legacy : {t_before * 1000 / n:.2f} ms/img  ({t_before:.3f}s)")
    print(f"  AFTER  _get_full_exif   : {t_after * 1000 / n:.2f} ms/img  ({t_after:.3f}s)")
    print(f"  speedup                 : {t_before / max(t_after, 1e-9):.2f}x")
    print(f"  saved_per_1000_photos   : {(t_before - t_after) / n * 1000:.1f}s")
    print(f"tmpdir={tmpdir}")


if __name__ == "__main__":
    main()
