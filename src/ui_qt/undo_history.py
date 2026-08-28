"""Persistent rename history stored in SQLite.

Every successful rename batch records the folder, timestamp, and a JSON
payload describing the old → new mapping.  The UI offers a dialog that
lists previous operations so the user can roll back any of them, not only
the most recent one.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from ..core.rename_report import undo_rename_operations

logger = logging.getLogger(__name__)

# Resolve the project root (src/ui_qt/ → src/ → project root) so the default
# DB path is always next to main.py, not relative to the current working dir.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DB_PATH = _PROJECT_ROOT / "logs" / "undo_history.sqlite"


@dataclass
class UndoEntry:
    id: int
    timestamp: float
    folder: str
    total: int
    mapping: Dict[str, str]  # nuevo -> original (basename or relative path)

    @property
    def timestamp_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.timestamp))


class UndoHistory:
    """Thin wrapper around an ``undo_history.sqlite`` database."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        folder TEXT NOT NULL,
        total INTEGER NOT NULL,
        mapping TEXT NOT NULL
    );
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(self.SCHEMA)
            conn.commit()

    @contextmanager
    def _connect(self):
        # timeout=5: wait up to 5 s if another process (e.g. antivirus, second
        # app instance) holds a write-lock instead of raising immediately.
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        try:
            yield conn
        finally:
            conn.close()

    def record(self, folder: str, mapping: Dict[str, str]) -> int:
        """Persist a rename batch. Returns the new row id."""
        if not mapping:
            return -1
        payload = json.dumps(mapping, ensure_ascii=False)
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO operations (ts, folder, total, mapping) VALUES (?, ?, ?, ?)",
                (time.time(), folder, len(mapping), payload),
            )
            conn.commit()
            return int(cur.lastrowid)

    @staticmethod
    def _normalize_folder(folder: str) -> str:
        return os.path.normcase(os.path.abspath(folder))

    def latest_for_folder(self, folder: str) -> Optional[UndoEntry]:
        """Return the most recent undo entry for ``folder``, if any."""
        target = self._normalize_folder(folder)
        for entry in self.list_entries(limit=100):
            if self._normalize_folder(entry.folder) == target:
                return entry
        return None

    def list_entries(self, limit: int = 50) -> List[UndoEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, ts, folder, total, mapping FROM operations "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        entries: List[UndoEntry] = []
        for row in rows:
            try:
                mapping = json.loads(row[4]) or {}
            except json.JSONDecodeError:
                mapping = {}
            entries.append(UndoEntry(id=row[0], timestamp=row[1], folder=row[2],
                                     total=row[3], mapping=mapping))
        return entries

    def delete(self, entry_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM operations WHERE id = ?", (entry_id,))
            conn.commit()


def apply_undo(entry: UndoEntry) -> Dict[str, int]:
    """Restore files for ``entry`` using relative-path-aware undo.

    Mapping keys may be legacy basenames or ``subdir/name.ext`` relative
    paths (forward slashes). Returns ``ok`` / ``missing`` / ``conflict``.
    """
    operations = list(entry.mapping.items())
    return undo_rename_operations(entry.folder, operations)
