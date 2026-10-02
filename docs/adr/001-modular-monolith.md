# ADR-001: Modular monolith (core + ui_qt)

## Status
Accepted

## Context
Renombrador PKS is a desktop batch tool for a small team. It needs reliable
spatial/EXIF logic and a responsive UI, without operational overhead of
multiple deployable services.

## Decision
Use a **modular monolith**:

- `src/core/` — domain logic (`RenamerLogic`, `SpatialCalculator`, config,
  rename reports). No PySide6 imports.
- `src/ui_qt/` — presentation, workers, undo SQLite UI, map WebEngine.
- `main.py` — thin entry point.

## Consequences
- **Easier**: single repo, single PyInstaller bundle, straightforward tests
  for core without a display server.
- **Harder**: scaling UI and core teams independently; any “second client”
  (CLI/API) must import `core` deliberately rather than calling widgets.
