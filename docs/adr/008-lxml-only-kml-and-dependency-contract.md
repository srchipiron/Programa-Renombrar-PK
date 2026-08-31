# ADR-008: lxml as the only KML parser, and dependency assumptions under test

## Status

Accepted — 2026-08-28

## Context

`_extract_linestring` was written as "try `fastkml`, fall back to raw XML".
Against the installed `fastkml` 1.4.0 that first branch raises on **every**
document: fastkml 1.x turned `KML.features()` into a plain list attribute, so
`list(k.features())` fails with `'list' object is not callable`. The exception
was caught and logged at debug level, so nothing ever surfaced.

Consequences measured on a real trace (`Tronco LAV Lorca Pulpí.kml`, 500 KiB,
348 vertices, 315 PK placemarks):

- `load_kml` spent **220 ms of 267 ms (82 %)** building a fastkml tree that was
  then thrown away.
- `fastkml` (and its `pygeoif` dependency) was carried in `requirements.txt`,
  in the PyInstaller `hiddenimports`, in the operator installer message and in
  the README, while contributing nothing.
- The code read as if fastkml covered KML dialects the XML path could not,
  which is the opposite of the truth.

Separately, both operator entry points (`INSTALAR_Y_EJECUTAR.bat` and
`ejecutar.bat`) run `pip install -r requirements.txt` on the operator's machine
with no lockfile, and CI does the same. The file pinned only `PySide6>=6.7`,
yet `SpatialCalculator.find_nearest_pk_name` does `int(tree.nearest(p))` and
indexes a list with the result — semantics introduced in **shapely 2.0**. On
shapely 1.x `nearest` returns the geometry and that call raises for every
photo. Nothing in the project stated that requirement.

## Decision

1. **Remove the fastkml branch and the dependency.** `lxml` parses the bytes
   once (`_parse_kml_xml` already strips namespaces for
   `_extract_named_points`) and an XPath for `.//LineString/coordinates` finds
   the trace regardless of folder nesting, `MultiGeometry` or namespace
   prefixes. Removal cannot change behaviour: the branch never returned.
2. **State the versions the code actually needs.** `shapely>=2.0` (STRtree
   index semantics) and `piexif>=1.1.3` (`piexif.helper.UserComment`,
   `insert(new_file=…)`), each with the reason inline. Dependencies whose
   floor could not be justified from the code were left unpinned rather than
   invented.
3. **Put those assumptions under test** (`tests/test_dependency_contract.py`)
   instead of adding a lockfile nobody would regenerate. CI installs the latest
   releases, so the contract tests are what turns a silent library change into
   a named failure: STRtree index semantics, linear referencing, perpendicular
   distance, `piexif.helper` unicode round-trip, `insert(new_file=…)`, and the
   Pillow `info['exif']` / `applist` access the EXIF hot path depends on.
4. **Pin the dialects in tests** (`tests/test_kml_dialects.py`): nested
   folders, `MultiGeometry`, prefixed namespaces, KMZ, axis synthesised from PK
   placemarks, empty document and malformed XML.

## Consequences

- `load_kml` on the reference trace: **267 ms → 55 ms (4.9×)**, identical
  output (348 vertices, 315 points, same PK extent). A second real file
  (`59634 Plataforma…kmz.kml`, 399 points) parses in 64 ms.
- One runtime dependency less to install in the field and to bundle in the
  ~700 MB PyInstaller output.
- A `piexif.helper` import failure used to downgrade EXIF `UserComment` to raw
  UTF-8 bytes silently, for a whole delivery. It now fails a test instead.
- Trade-off: if a future KML dialect ever needs a real KML object model, it has
  to be reintroduced deliberately — with a call site that actually works.
  `test_parser_does_not_depend_on_fastkml` documents that this is a decision,
  not an oversight.
- Trade-off: contract tests couple the suite to library behaviour, so a
  legitimate upstream change will fail CI. That is the intent: the failure
  names the assumption instead of surfacing as a `TypeError` mid-analysis.
