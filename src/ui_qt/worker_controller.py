"""Owns the single active background worker for the Qt UI.

Keeps start / cancel / clear out of ``MainWindow`` so the busy gate and
thread lifecycle can be unit-tested without spinning the full window.
"""
from __future__ import annotations

from typing import Callable, Optional

from .workers import _BaseWorker, run_worker


class WorkerController:
    """At most one cooperative worker may run at a time."""

    def __init__(
        self,
        *,
        on_started: Optional[Callable[[str], None]] = None,
        on_cleared: Optional[Callable[[], None]] = None,
    ) -> None:
        self._current: Optional[_BaseWorker] = None
        self._on_started = on_started
        self._on_cleared = on_cleared

    @property
    def current(self) -> Optional[_BaseWorker]:
        return self._current

    @property
    def busy(self) -> bool:
        return self._current is not None

    def start(self, worker: _BaseWorker, message: str) -> bool:
        """Launch ``worker`` if idle. Returns False when another job is running."""
        if self._current is not None:
            return False
        self._current = worker
        if self._on_started is not None:
            self._on_started(message)
        run_worker(worker, callback=self.clear)
        return True

    def cancel(self) -> bool:
        """Request cooperative cancellation. Returns False if idle."""
        if self._current is None:
            return False
        self._current.cancel()
        return True

    def clear(self) -> None:
        """Mark the controller idle (called from the GUI thread after run)."""
        self._current = None
        if self._on_cleared is not None:
            self._on_cleared()
