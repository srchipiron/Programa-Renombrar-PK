"""Generate the application icon bundle from a source PNG.

Produces:
    src/assets/branding/icon_source.png   (cropped square, 1024x1024, RGBA)
    src/assets/branding/app_icon.ico      (multi-resolution Windows icon)

The script is designed for sources produced by a generative image model, which
usually come back as an RGB JPEG-style PNG with a solid chroma-key background
(magenta) or with a fake "checkerboard transparency" pattern baked into the
pixels.  The pipeline:

    1.  Crop to the rectangle that contains the chroma-key background.
    2.  Remove the chroma-key so the icon becomes real RGBA with alpha=0
        outside the tile.
    3.  Trim surrounding transparent rows/columns.
    4.  Force a square 1024x1024 canvas.
    5.  Emit a multi-resolution ``.ico``.

Run with:
    python scripts/make_icon.py [path/to/source.png] [--chroma r,g,b]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Tuple

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRANDING = ROOT / "src" / "assets" / "branding"
BRANDING.mkdir(parents=True, exist_ok=True)

RAW_CANDIDATES = [
    BRANDING / "icon_source_raw.png",
    Path(
        r"C:\Users\JavierAL\.cursor\projects\g-AEROSCAN-2026-Programa-Renombrar-PK"
        r"\assets\icon_source_raw.png"
    ),
    Path(
        r"C:\Users\JavierAL\.cursor\projects\g-AEROSCAN-2026-Programa-Renombrar-PK"
        r"\assets\icon_source.png"
    ),
]

ICON_SIZES = [256, 128, 64, 48, 32, 24, 16]


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------
def _locate_source(user_arg: str | None) -> Path:
    if user_arg:
        p = Path(user_arg).expanduser().resolve()
        if p.is_file():
            return p
        raise FileNotFoundError(p)

    for candidate in RAW_CANDIDATES:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "No icon source found. Pass a PNG path as the first argument or drop "
        f"one at {BRANDING / 'icon_source_raw.png'}."
    )


# ---------------------------------------------------------------------------
# Chroma key helpers
# ---------------------------------------------------------------------------
def _find_chroma_bbox(
    img: Image.Image,
    chroma: Tuple[int, int, int],
    tolerance: int = 25,
) -> Tuple[int, int, int, int] | None:
    """Return the bbox of the DOMINANT chroma block.

    Generator outputs occasionally contain scattered chroma-coloured pixels
    near the image edges (compression ringing, blurry side-fills, ...).  To
    isolate the real keying block we:

    1.  Collect the set of all chroma pixels (within ``tolerance``).
    2.  For each row and column, count how many chroma pixels it contains.
    3.  Keep only rows/columns whose chroma density is above 50 % of the
        maximum.
    4.  Return the bbox of that dense region.
    """
    rgb = img.convert("RGB")
    data = rgb.load()
    w, h = rgb.size
    tr, tg, tb = chroma
    row_counts = [0] * h
    col_counts = [0] * w
    for y in range(h):
        for x in range(w):
            r, g, b = data[x, y]
            if (
                abs(r - tr) <= tolerance
                and abs(g - tg) <= tolerance
                and abs(b - tb) <= tolerance
            ):
                row_counts[y] += 1
                col_counts[x] += 1
    if not any(row_counts) or not any(col_counts):
        return None
    row_thr = max(row_counts) * 0.5
    col_thr = max(col_counts) * 0.5
    ys = [y for y, c in enumerate(row_counts) if c >= row_thr]
    xs = [x for x, c in enumerate(col_counts) if c >= col_thr]
    if not xs or not ys:
        return None
    return (min(xs), min(ys), max(xs) + 1, max(ys) + 1)


def _remove_chroma(
    img: Image.Image,
    chroma: Tuple[int, int, int],
    tolerance: int = 40,
    feather: int = 2,
) -> Image.Image:
    """Replace near-chroma pixels with alpha=0 and suppress colour bleeding."""
    src = img.convert("RGBA")
    pixels = src.load()
    tr, tg, tb = chroma
    tol_sq = tolerance * tolerance * 3
    w, h = src.size
    for y in range(h):
        for x in range(w):
            r, g, b, _ = pixels[x, y]
            dr, dg, db = r - tr, g - tg, b - tb
            dist_sq = dr * dr + dg * dg + db * db
            if dist_sq <= tol_sq:
                pixels[x, y] = (0, 0, 0, 0)
            elif feather and dist_sq <= tol_sq * 4:
                scale = (dist_sq - tol_sq) / (tol_sq * 3)
                alpha = max(0, min(255, int(255 * scale)))
                pixels[x, y] = (r, g, b, alpha)
    return src


# ---------------------------------------------------------------------------
# Cropping helpers
# ---------------------------------------------------------------------------
def _trim_transparent_border(img: Image.Image, margin_pct: float = 0.04) -> Image.Image:
    if img.mode != "RGBA":
        return img
    bbox = img.split()[-1].getbbox()
    if not bbox:
        return img
    cropped = img.crop(bbox)
    cw, ch = cropped.size
    side = max(cw, ch)
    margin = int(side * margin_pct)
    canvas = Image.new("RGBA", (side + margin * 2, side + margin * 2), (0, 0, 0, 0))
    canvas.paste(cropped, (margin + (side - cw) // 2, margin + (side - ch) // 2), cropped)
    return canvas


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _parse_chroma(value: str) -> Tuple[int, int, int]:
    parts = [int(p) for p in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("chroma must be r,g,b")
    return tuple(parts)  # type: ignore[return-value]


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="Source PNG path")
    parser.add_argument(
        "--chroma",
        type=_parse_chroma,
        default=(255, 0, 255),
        help="Chroma-key colour (default: 255,0,255 / magenta). Pass 0,0,0,0 "
        "after the other args to skip keying.",
    )
    parser.add_argument(
        "--no-chroma",
        action="store_true",
        help="Skip chroma-keying; assume the source is already RGBA transparent.",
    )
    args = parser.parse_args(list(argv))

    source = _locate_source(args.source)
    print(f"[icon] source   = {source}")

    img = Image.open(source)
    print(f"[icon] original = {img.size}  mode={img.mode}")

    if not args.no_chroma:
        bbox = _find_chroma_bbox(img, args.chroma)
        if bbox:
            print(f"[icon] chroma bbox = {bbox}")
            img = img.crop(bbox)
        img = _remove_chroma(img, args.chroma)

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    img = _trim_transparent_border(img)
    img = img.resize((1024, 1024), Image.LANCZOS)

    png_out = BRANDING / "icon_source.png"
    img.save(png_out, format="PNG", optimize=True)
    print(f"[icon] wrote    {png_out}  ({png_out.stat().st_size / 1024:.1f} KB)")

    ico_out = BRANDING / "app_icon.ico"
    img.save(
        ico_out,
        format="ICO",
        sizes=[(s, s) for s in ICON_SIZES],
    )
    print(f"[icon] wrote    {ico_out}  ({ico_out.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
