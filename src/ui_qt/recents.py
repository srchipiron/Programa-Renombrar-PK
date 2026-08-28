"""Pure helpers for bounded most-recently-used (MRU) lists."""
from __future__ import annotations

from typing import List


def push_recent(current: List[str], value: str, max_items: int) -> List[str]:
    """Return a new list with ``value`` moved to the front, capped at ``max_items``.

    ``current`` is not mutated. Empty/falsy ``value`` returns a shallow copy
    of ``current`` unchanged.
    """
    if not value:
        return list(current)
    updated = [v for v in current if v != value]
    updated.insert(0, value)
    return updated[: max(0, max_items)]
