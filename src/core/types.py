"""Shared typed payloads crossing core ↔ UI boundaries."""
from __future__ import annotations

from typing import Dict, TypedDict


class RenameStats(TypedDict, total=False):
    ok: int
    errors: int
    skipped: int
    cancelled: int
    mapping: Dict[str, str]
