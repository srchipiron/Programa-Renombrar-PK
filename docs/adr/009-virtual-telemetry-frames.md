# ADR-009: Telemetry frames are analysis evidence, not rename targets

## Status

Accepted — 2026-08-28

## Context

`VideoExtractor.parse_srt` turns each DJI/Autel SRT cue into a `PhotoItem` so
video flights contribute PK evidence. Every frame was stamped with
`path = <the .srt file>` and `name = Frame_<HHMMSS>.jpg`, and
`_on_import_video` appends them straight into `_analysis_items` — the same list
F7 renames. Reproduced on a four-cue SRT:

- The preview plan is a `{path: filename}` mapping, so four rows collapsed to
  **one** entry: the table showed the same proposed name on every frame.
- `_build_rename_jobs` produced one job per frame whose *source path was the
  operator's `.srt`*. `process_images` renamed that file to `PK-….jpg`, failed
  to write EXIF into a text file and rolled the name back: `{'ok': 0,
  'errors': 4}` for a four-cue import. The telemetry file survived only
  because the rollback worked; a locked file (antivirus, OneDrive) would have
  left it named `.jpg`.
- DJI writes ~30 cues per second, so `Frame_<HHMMSS>.jpg` also collided in
  batches of ~30.

## Decision

`PhotoItem` gains `virtual: bool`. Frames are `virtual=True` and get a unique
synthetic path `<srt>#NNNNNN` plus an index-suffixed name.

- `build_preview_names` computes `is_inside_threshold` and `pk_display` for
  them (they are coverage evidence) but never assigns `new_name_base`.
- `_build_rename_jobs` skips them explicitly as well — F7 must not be one
  refactor away from touching a path that names no file.
- The preview column shows `(fotograma de vídeo — no se renombra)` instead of
  the misleading `(fuera de umbral)`.
- The "para renombrar" counters in the sidebar banner and status bar exclude
  them, so the number matches what F7 will actually do.
- `SessionStore.load` keeps virtual items regardless of `os.path.exists`:
  their position lives in the session, and the existence filter would
  otherwise drop every frame — and discard a session holding only frames.

## Consequences

- Importing an SRT and pressing F7 is now a no-op for those rows instead of a
  batch of errors that renames the telemetry file back and forth.
- Coverage QA (ADR-007) keeps counting frames, which is the reason to import
  them: a video pass over a stretch with no stills still proves coverage.
- Trade-off: `path` no longer points at a real file for these items, so any
  future code must check `virtual` before touching the filesystem. The
  existence filter in `SessionStore` was exactly that trap, and the regression
  test suite covers it.
- Trade-off: sessions saved by older builds carry frames without the flag;
  they restore as ordinary items pointing at the `.srt`. Re-importing the SRT
  refreshes them.
