# ADR-003: Long work off the UI thread via Qt workers

## Status
Accepted

## Context
Analysis and rename perform heavy EXIF I/O and filesystem operations. Blocking
the Qt event loop freezes the map, progress bar, and cancel affordance.

## Decision
Run analysis, rename, undo, and auto-threshold in **daemon threads** started
from `ui_qt.workers`, communicating back through Qt signals (`progress`,
`finished`, `failed`). Core APIs accept optional `progress_cb` / `check_cancel`
for cooperative cancellation.

## Consequences
- **Easier**: responsive UI, familiar pattern for PySide6 apps.
- **Harder**: callers must treat `PhotoItem` lists as owned by the UI session
  until workers complete; no automatic transaction rollback on partial rename
  (documented in user help and surfaced via the post-rename recovery dialog).
- **Lifecycle**: `WorkerController` owns the single active worker; autosave is
  paused while a worker runs so session snapshots do not race with FS updates.
