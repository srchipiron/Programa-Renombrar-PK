"""Pure (Qt-free) persistence for the last analysis session.

Extracted out of :class:`~src.ui_qt.main_window.MainWindow` so the
save/restore logic can be unit-tested without booting a ``QApplication``
and so ``MainWindow`` stays focused on wiring widgets and workers.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from ..core.models import PhotoItem
from ..core.paths import logs_dir

logger = logging.getLogger(__name__)

# Written to the app's data directory (see ``core.paths``): next to the
# executable when writable, under %LOCALAPPDATA% for an installed copy.
DEFAULT_SESSION_PATH = logs_dir() / "last_session.json"

#: Field names accepted by :class:`PhotoItem`, used to drop stale keys from
#: sessions saved by older app versions instead of failing to restore.
_PHOTO_ITEM_FIELDS = {f.name for f in PhotoItem.__dataclass_fields__.values()}  # type: ignore[attr-defined]


class SessionStore:
    """Persists and restores the last analyzed folder/KML/items to disk."""

    def __init__(self, path: Path = DEFAULT_SESSION_PATH) -> None:
        self.path = path

    def save(self, folder: str, kml_file: str, items: List[PhotoItem]) -> None:
        """Write the current session to disk. No-op when there's nothing to save."""
        if not items:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "folder": folder,
                "kml": kml_file,
                "items": [asdict(it) for it in items],
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
        except OSError:
            logger.exception("Failed to autosave session to %s", self.path)

    def load(self) -> Dict[str, Any]:
        """Return the last saved session, filtered to items still usable.

        The returned dict has keys ``folder``, ``kml``, ``items``
        (``List[PhotoItem]``), ``restored_count`` and ``total_count``. An
        empty dict is returned when there's no usable session (missing
        file, corrupt JSON, or none of the referenced photos exist anymore).
        """
        try:
            if not self.path.exists():
                return {}
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.exception("Failed to read session file %s", self.path)
            return {}

        items_raw = payload.get("items") or []
        if not items_raw:
            return {}

        restored: List[PhotoItem] = []
        for raw in items_raw:
            if not isinstance(raw, dict):
                continue
            try:
                restored.append(PhotoItem(**raw))
            except TypeError:
                # Older session file with fields since removed/renamed.
                restored.append(PhotoItem(**{k: v for k, v in raw.items() if k in _PHOTO_ITEM_FIELDS}))

        # Telemetry frames (SRT import) carry their position in the session
        # itself and have no file on disk, so the existence check would drop
        # every one of them — and the whole session when it holds only frames.
        existing = [it for it in restored if it.virtual or os.path.exists(it.path)]
        if not existing:
            return {}

        return {
            "folder": (payload.get("folder") or "").strip(),
            "kml": (payload.get("kml") or "").strip(),
            "items": existing,
            "restored_count": len(existing),
            "total_count": len(restored),
        }
