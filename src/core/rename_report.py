"""Rename report CSV — single source for path and mapping I/O."""
from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

logger = logging.getLogger(__name__)

RENAME_REPORT_FILENAME = "reporte_renombrado.csv"
# (nuevo, original) — basename-only (legacy) or relative paths with `/`.
RenameOperation = Tuple[str, str]


def report_csv_path(base_folder: str | Path) -> Path:
    return Path(base_folder) / RENAME_REPORT_FILENAME


def normalize_mapping_key(value: str) -> str:
    """Normalize a mapping key to portable forward-slash relative form."""
    text = (value or "").strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def relative_mapping_key(path: str | Path, base_folder: str | Path) -> str:
    """Return ``path`` relative to ``base_folder`` using forward slashes."""
    try:
        rel = os.path.relpath(str(path), str(base_folder))
    except ValueError:
        # Different drive letters on Windows — fall back to basename.
        return os.path.basename(str(path))
    return normalize_mapping_key(rel)


def load_rename_operations(base_folder: str | Path) -> List[RenameOperation]:
    """Return all ``(nuevo, original)`` pairs in CSV order (duplicates preserved)."""
    path = report_csv_path(base_folder)
    if not path.is_file():
        return []
    operations: List[RenameOperation] = []
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                original = normalize_mapping_key(row.get("original") or "")
                nuevo = normalize_mapping_key(row.get("nuevo") or "")
                if original and nuevo:
                    operations.append((nuevo, original))
    except OSError as exc:
        logger.warning("Could not read rename report %s: %s", path, exc)
    return operations


def save_rename_report(base_folder: str | Path, rows: Sequence[Dict[str, Any]]) -> Path:
    """Save rename report rows using utf-8-sig for perfect Excel compatibility on Windows.

    Writes to a sibling temp file and promotes with ``os.replace`` so a crash
    mid-write cannot leave an empty/truncated CSV while files are already renamed.
    """
    path = report_csv_path(base_folder)
    tmp_path = path.with_suffix(path.suffix + ".__tmp__")
    try:
        with open(tmp_path, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["original", "nuevo", "pk", "distancia"])
            writer.writeheader()
            for r in rows:
                writer.writerow({
                    "original": normalize_mapping_key(str(r.get("original", ""))),
                    "nuevo": normalize_mapping_key(str(r.get("nuevo", ""))),
                    "pk": r.get("pk", ""),
                    "distancia": r.get("distancia", ""),
                })
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
    except Exception:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise
    return path


def load_rename_mapping(base_folder: str | Path) -> Dict[str, str]:
    """Return ``nuevo -> original`` (last CSV row wins on duplicates)."""
    mapping: Dict[str, str] = {}
    for nuevo, original in load_rename_operations(base_folder):
        mapping[nuevo] = original
    return mapping


def undo_rename_operations(
    base_folder: str | Path,
    operations: Sequence[RenameOperation],
) -> Dict[str, int]:
    """Revert ``(nuevo, original)`` pairs under ``base_folder``.

    Supports:
    - **Legacy** basename-only keys: locate ``nuevo`` anywhere under the tree
      (except ``_backup_originales``) and rename in its current parent.
    - **Relative paths** (contain ``/``): move ``base/nuevo`` back to
      ``base/original``, creating parent folders as needed.
    - Nested ``nuevo`` + basename-only ``original``: restore to ``base/original``
      (root of the work folder), not next to the nested file.

    ``operations`` arrive in rename order and are **replayed backwards**: a
    batch may free a name and then reuse it (``A→B`` followed by ``C→A``), so
    undoing forwards would try to restore ``B→A`` while ``A`` is still taken
    and report a conflict for a batch that is perfectly reversible. Last in,
    first out is the only order that inverts a sequence of moves.

    Returns ``{ok, missing, conflict}``.
    """
    base = Path(base_folder)
    summary = {"ok": 0, "missing": 0, "conflict": 0}
    if not base.is_dir():
        return summary

    # Duplicate basenames (same new name in two subfolders) carry no directory
    # in legacy rows, so the Nth row is paired with the Nth walk occurrence.
    # Rows are consumed backwards, so the buckets are consumed backwards too:
    # that keeps the pairing identical while fixing chained renames.
    index: Dict[str, List[Path]] = {}
    for root, _dirs, files in os.walk(base):
        if "_backup_originales" in root:
            continue
        for name in files:
            index.setdefault(name, []).append(Path(root) / name)

    for new_key, old_key in reversed(list(operations)):
        new_n = normalize_mapping_key(new_key)
        old_n = normalize_mapping_key(old_key)
        if not new_n or not old_n:
            continue

        src: Path | None = None
        if "/" in new_n:
            candidate = base / Path(*new_n.split("/"))
            if candidate.is_file():
                src = candidate
                bucket = index.get(candidate.name)
                if bucket and src in bucket:
                    bucket.remove(src)
            else:
                # File moved after the report; fall back to basename search.
                bucket = index.get(Path(new_n).name, [])
                if bucket:
                    src = bucket.pop()
        else:
            bucket = index.get(new_n, [])
            if bucket:
                src = bucket.pop()

        if src is None:
            summary["missing"] += 1
            continue

        target = _resolve_undo_target(base, src, new_n, old_n)

        try:
            if target.exists() and target.resolve() != src.resolve():
                summary["conflict"] += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src.rename(target)
            summary["ok"] += 1
        except OSError as exc:
            logger.warning("Undo failed for %s -> %s: %s", src, target, exc)
            summary["conflict"] += 1

    return summary


def _resolve_undo_target(
    base: Path,
    src: Path,
    new_n: str,
    old_n: str,
) -> Path:
    """Choose the restore path for one undo operation.

    - Relative ``original`` (contains ``/``) → ``base/original``.
    - Nested ``nuevo`` + basename-only ``original`` → original lived at the
      folder root (``relative_mapping_key`` omits ``./``), so restore to
      ``base/original`` — *not* ``src.parent/original``.
    - Legacy basename-only pair → rename in the directory where ``nuevo``
      was found (historical behaviour).
    """
    if "/" in old_n:
        return base / Path(*old_n.split("/"))
    if "/" in new_n:
        return base / old_n
    return src.parent / old_n

