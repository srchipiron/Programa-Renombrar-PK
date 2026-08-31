# ADR-012: Portable-first data directory, and one command per delivery form

## Status

Accepted — 2026-08-28

## Context

The app had to become something you can hand to a colleague: "si le mando la
carpeta, que pueda ejecutarlo". Two things stood in the way.

**Everything writable lived next to `main.py`.** `config.json`, `logs/`,
`undo_history.sqlite`, `last_session.json` and the new `proyectos/` all
resolved through `Path(__file__).resolve().parents[2]`. That is correct when
running from source and wrong in both distribution modes:

- frozen, the path points *inside* the bundle rather than at the application;
- installed under `C:\Program Files`, the folder is read-only, so the app could
  not save its configuration, its undo history or its projects at all.

`initialize_logging` was worse: its default `log_dir="logs"` is relative to the
**working directory**, so logs landed wherever the shortcut happened to start.

**Only one delivery form was scripted.** `build.bat` produced the PyInstaller
folder; the Inno Setup script existed but nothing ran it, and there was no
archive to actually send.

## Decision

1. **`core/paths.py`** resolves three questions once: where the app lives
   (`app_dir`), where its bundled read-only files are (`resource_dir`, i.e.
   `sys._MEIPASS` when frozen) and where it may write (`data_dir`).
2. **Portable first.** `data_dir()` probes the application folder by actually
   creating a file — permission bits lie on Windows — and uses it when it can.
   A copied folder or a USB stick therefore carries its own settings. Only when
   that fails does it fall back to `%LOCALAPPDATA%\RenombradorPKS`, which is
   what an installed-under-Program-Files copy hits.
3. `config.example.json` ships **inside** the bundle and is read through
   `resource_dir()`, so a first run on a clean PC still bootstraps a config.
4. **The spec derives its hidden imports from the source tree.** The
   hand-written list had already gone stale — it was missing every module added
   since it was written (`projects`, `coverage`, `paths`, `orientation`, …).
5. **`build.bat` produces all three forms**: the portable folder, a ZIP of it
   (via `tar`, which ships with Windows 10/11 and is far faster than
   `Compress-Archive`), and the installer when Inno Setup is present — printing
   the `winget` line and continuing when it is not.

## Consequences

- The same build works copied to a pen drive, unzipped on a desktop, or
  installed; the operator does not have to know which mode they are in.
- Positive: no new runtime dependency. The probe is a single temp file at
  startup and the answer is cached.
- Trade-off: the two modes differ in where settings end up, which can confuse
  someone looking for `config.json` after an installed run. The chosen
  directory is logged at INFO on startup for that reason.
- Trade-off: the bundle is ~700 MB because QtWebEngine ships whole for the
  embedded map. A map-less variant would be a fraction of that, but
  `map_tab.py` imports `QtWebEngineWidgets` at module scope, so it would crash
  on launch rather than degrade; making that import lazy is the prerequisite.
- Projects and config are deliberately **not** bundled: a colleague receives a
  clean program, and moving a corridor over is copying `proyectos\*.json`.
