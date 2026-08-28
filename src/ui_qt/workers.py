"""Background workers for the Qt UI.

Each worker wraps a long-running core operation in a QObject with well-defined
signals so the UI thread can react to progress, completion and failure safely.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable, Dict, List, Optional

from PySide6.QtCore import QObject, Signal

from ..core.models import PhotoItem
from ..core.renamer_logic import RenamerLogic, compute_suggested_threshold
from ..core.spatial_calculator import SpatialCalculator
from .undo_history import UndoEntry, apply_undo

logger = logging.getLogger(__name__)


class _BaseWorker(QObject):
    """Base worker emitting standard signals.

    Signals
    -------
    progress(int, int, str): completed, total, message
    finished(object):        payload specific to each worker
    failed(str):             error message
    """

    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Request cooperative cancellation of the current operation."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()


class AnalysisWorker(_BaseWorker):
    """Runs EXIF extraction + spatial calculations for a folder.

    Uses dedicated core instances so background threads never mutate the
    ``SpatialCalculator`` / ``RenamerLogic`` owned by the UI thread.
    """

    def __init__(
        self,
        folder: str,
        kml_path: Optional[str],
        *,
        max_workers: int = 4,
        tukey_multiplier: float = 1.5,
        extra_landmarks: Optional[List[Dict[str, Any]]] = None,
        landmark_kmls: Optional[List[str]] = None,
        landmark_groups: Optional[List[Dict[str, Any]]] = None,
        landmark_capture_radius: float = 300.0,
        landmark_cluster_radius: float = 500.0,
        landmark_split_ratio: float = 0.45,
        viaduct_pks: Optional[List[str]] = None,
        spatial_calc: Optional[SpatialCalculator] = None,
        renamer: Optional[RenamerLogic] = None,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.folder = folder
        self.kml_path = kml_path
        self.max_workers = max_workers
        self.tukey_multiplier = tukey_multiplier
        self.extra_landmarks = list(extra_landmarks or [])
        self.landmark_kmls = list(landmark_kmls or [])
        self.landmark_groups = list(landmark_groups or [])
        self.landmark_capture_radius = landmark_capture_radius
        self.landmark_cluster_radius = landmark_cluster_radius
        self.landmark_split_ratio = landmark_split_ratio
        self.viaduct_pks = list(viaduct_pks or [])
        self._spatial_calc = spatial_calc
        self._renamer = renamer

    def run(self) -> None:
        try:
            spatial_calc = self._spatial_calc or SpatialCalculator()
            renamer = self._renamer or RenamerLogic(
                spatial_calc,
                max_workers=self.max_workers,
                tukey_multiplier=self.tukey_multiplier,
            )
            if self.kml_path:
                spatial_calc.load_kml(self.kml_path)
            if self.extra_landmarks:
                spatial_calc.add_landmarks_from_dicts(self.extra_landmarks)
            for kml_path in self.landmark_kmls:
                try:
                    spatial_calc.add_landmarks_from_kml(kml_path)
                except Exception:
                    logger.warning("No se pudieron cargar landmarks de %s", kml_path)
            if self.landmark_groups:
                spatial_calc.set_landmark_groups(self.landmark_groups)
            if self.landmark_capture_radius > 0:
                spatial_calc.set_landmark_capture_radius(self.landmark_capture_radius)
            spatial_calc.set_landmark_cluster_params(
                cluster_radius_m=self.landmark_cluster_radius,
                split_ratio=self.landmark_split_ratio,
            )
            if self.viaduct_pks:
                renamer.set_viaduct_pks(self.viaduct_pks)

            def _cb(done: int, total: int, msg: str) -> None:
                if self.is_cancelled():
                    raise _Cancelled()
                self.progress.emit(done, total, msg)

            try:
                result = renamer.analyze_distance_stats(self.folder, progress_cb=_cb)
            except _Cancelled:
                self.finished.emit({"cancelled": True, "items": []})
                return

            if self.kml_path:
                result["kml_path"] = self.kml_path
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Analysis worker failed")
            self.failed.emit(str(exc))


class RenameWorker(_BaseWorker):
    """Runs the rename pipeline for a set of prepared items."""

    def __init__(
        self,
        items: List[PhotoItem],
        base_folder: str,
        create_backup: bool,
        renamer: RenamerLogic,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.items = items
        self.base_folder = base_folder
        self.create_backup = create_backup
        self.renamer = renamer

    def run(self) -> None:
        try:
            stats = self.renamer.process_images(
                self.items,
                self.base_folder,
                self.create_backup,
                progress_cb=lambda d, t, m: self.progress.emit(d, t, m),
                check_cancel=self.is_cancelled,
            )
            self.finished.emit(stats)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Rename worker failed")
            self.failed.emit(str(exc))


class UndoHistoryWorker(_BaseWorker):
    """Reverts a rename batch stored in the SQLite undo history."""

    def __init__(self, entry: UndoEntry, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.entry = entry

    def run(self) -> None:
        try:
            summary = apply_undo(self.entry)
            ok = summary["ok"] > 0
            msg = (
                f"Revertidas: {summary['ok']} · "
                f"No encontradas: {summary['missing']} · "
                f"Conflictos: {summary['conflict']}"
            )
            self.finished.emit({"ok": ok, "message": msg, "summary": summary, "entry_id": self.entry.id})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Undo history worker failed")
            self.failed.emit(str(exc))


class UndoWorker(_BaseWorker):
    """Reverts a previous rename operation using reporte_renombrado.csv."""

    def __init__(
        self,
        base_folder: str,
        renamer: RenamerLogic,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.base_folder = base_folder
        self.renamer = renamer

    def run(self) -> None:
        try:
            ok, message = self.renamer.undo_last_rename_from_csv(
                self.base_folder,
                progress_cb=lambda d, t, m: self.progress.emit(d, t, m),
            )
            self.finished.emit({"ok": ok, "message": message})
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Undo worker failed")
            self.failed.emit(str(exc))


class AutoThresholdWorker(_BaseWorker):
    """Compute an automatic threshold from a collection of distances.

    We keep this out of the UI thread because the item list can be large and
    the UI could block computing stats.
    """

    def __init__(
        self,
        items: List[PhotoItem],
        *,
        tukey_multiplier: float = 1.5,
        parent: Optional[QObject] = None,
    ):
        super().__init__(parent)
        self.items = items
        self.tukey_multiplier = tukey_multiplier

    def run(self) -> None:
        try:
            distances = [it.distance for it in self.items if it.distance != float("inf")]
            stats = compute_suggested_threshold(
                distances, tukey_multiplier=self.tukey_multiplier
            )
            payload = dict(stats)
            # ``threshold`` kept for backwards compatibility with existing
            # consumers.  ``None`` means "no usable samples".
            payload["threshold"] = stats["suggested"] if stats["samples"] > 0 else None
            self.finished.emit(payload)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Auto threshold worker failed")
            self.failed.emit(str(exc))


class _Cancelled(Exception):
    """Internal marker used to abort cooperative loops."""


class _CallbackBridge(QObject):
    """Marshals a plain callback from a worker thread onto the GUI thread.

    ``QTimer.singleShot`` requires a running Qt event loop on the *calling*
    thread to ever fire, so scheduling it from a plain ``threading.Thread``
    (no event loop) means the callback silently never runs. A real Qt signal
    uses automatic queued connections instead, which Qt marshals correctly
    based on the *receiver's* thread affinity regardless of which thread
    emits it -- the same mechanism already used by ``progress``/``finished``.
    """

    triggered = Signal()

    def __init__(self, callback: Callable[[], None], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.triggered.connect(callback)

    def fire(self) -> None:
        self.triggered.emit()


def run_worker(worker: _BaseWorker, callback: Optional[Callable[[], None]] = None) -> None:
    """Launch ``worker.run`` in a dedicated daemon thread.

    Worker completion callbacks are marshalled back onto the Qt GUI thread
    via a queued signal connection so callers can safely touch widgets.
    """
    # Parented to ``worker`` (created on the GUI thread) so the bridge can't
    # be garbage-collected mid-flight while the background thread is running.
    bridge = _CallbackBridge(callback, parent=worker) if callback is not None else None

    def _target():
        try:
            worker.run()
        finally:
            if bridge is not None:
                bridge.fire()

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
