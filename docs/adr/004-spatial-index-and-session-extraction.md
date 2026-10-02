# ADR-004: Spatial index for nearest-PK and Qt-free session/recents extraction

## Status
Accepted

## Context
Two maintainability/performance issues surfaced during a full-codebase audit
(2026-07):

1. `SpatialCalculator.find_nearest_pk_name` scanned every named KML point with
   a haversine calculation for **every analyzed photo** — O(photos × points).
   Traces with hundreds of PK markers and thousands of photos made analysis
   noticeably slower than it needed to be.
2. `mark_duplicates` compared each candidate photo against every previously
   "kept" photo — O(n × kept) in the worst case (no duplicates, the common
   case), which degrades on large batches.
3. `MainWindow` had accumulated autosave/session-restore and MRU
   ("recent folders/KMLs") logic inline, mixing pure data transformations
   with Qt widget wiring and making that logic hard to unit-test without a
   `QApplication`.

## Decision
1. **Spatial index**: `SpatialCalculator` now builds an
   [`shapely.strtree.STRtree`](https://shapely.readthedocs.io/) over the
   named points projected into the same local equirectangular metric frame
   already used for chainage (`calculate_pk`/`distance_to_axis`). Nearest-PK
   lookups are now O(log n) and use a single consistent distance metric
   instead of mixing haversine (points) with equirectangular (axis). The
   local frame now derives its reference centroid from the axis *or* the
   named points, so point-only KML/GeoJSON files (no `LineString`) still get
   an accurate metric frame.
2. **Bucketed duplicate detection**: `mark_duplicates` now buckets candidates
   on a `gps_tolerance_m`-sized grid keyed by capture date, checking only the
   3×3 neighborhood of cells instead of the full "kept" list. This keeps
   large batches close to O(n) while producing identical results for the
   tolerances used in practice (a duplicate's GPS delta can't exceed one grid
   cell by construction).
3. **Session/recents extraction**: `MainWindow._save_session` /
   `_restore_last_session` moved to `ui_qt/session_store.py`
   (`SessionStore`, Qt-free, unit-tested directly). The MRU list mutation
   used by "recent folders/KMLs" moved to `ui_qt/recents.py`
   (`push_recent`, pure function). `MainWindow` now only wires these to
   widgets/signals instead of owning the logic.

## Consequences
- **Easier**: analysis scales to large PK traces/photo batches without a
  linear-in-points or quadratic-in-photos penalty; session persistence and
  MRU logic can be tested without booting Qt; `MainWindow` is smaller and
  more focused on wiring.
- **Harder**: nearest-PK distance is now always the local equirectangular
  metric (matching the axis/chainage math) rather than true haversine great-
  circle distance. This is a deliberate simplification — traces are local
  (single infrastructure project, a few km wide) so the difference is
  negligible, and it removes a previous inconsistency where axis distance
  and point distance used two different metrics.
