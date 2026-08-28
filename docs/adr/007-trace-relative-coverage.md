# ADR-007: Coverage measured against the trace, with a cadence-aware gap threshold

## Status

Accepted — 2026-08-27

## Context

ADR-005 added coverage QA: holes between consecutive photos, reported when the
chainage delta reached a fixed 100 m. Running it against a real delivery
(238 photos of the Lorca–Pulpí trace, `Tronco LAV Lorca Pulpí.kml`, 315 PK
placemarks over 31 km) exposed two problems:

1. **The trace itself was invisible.** Gaps were only measured *between*
   photos, so a flight that stopped 2 km short of the end, or started 2 km late,
   reported "sin huecos". The question operators actually need answered before
   leaving the site — "did we cover the whole corridor?" — was not being asked.
2. **The fixed 100 m threshold was noise.** That flight shoots every ~148 m
   (median; p90 193 m), so *every* normal interval crossed the threshold:
   **190 "gaps"** on a healthy survey. A signal that fires on every interval
   carries no information, and it buried the one interval that mattered.

A third problem appeared while fixing the first: crediting each photo with a
single point of chainage makes "covered metres" ≈ 0 for any real corridor
flight, so a naive coverage ratio read 5 % on a survey that photographed the
whole trace.

## Decision

1. **Trace extent.** `SpatialCalculator.axis_pk_extent()` returns the official
   PK of the axis endpoints through the same calibration used for photos
   (falling back to the span of PK placemarks when the file has no centreline).
   `compute_coverage(spatial_calc=…)` uses it to emit **head** and **tail**
   gaps alongside interior ones, each tagged with its `kind`.
2. **Coverage = footprint union.** Each photo is credited with
   ±`pk_tolerance_m` (default 50 m — half the usual PK post spacing) of trace;
   the intervals are merged and clipped to the trace. Reported as
   `covered_m` / `coverage_ratio`. On the reference delivery this reads 65 %,
   matching what a GIS overlay shows, instead of 5 %.
3. **Cadence-aware gap threshold.** `suggest_gap_min()` returns
   `max(100 m, 2.5 × median photo spacing)`, excluding sub-5 m deltas so
   TI/CEN/TD bursts at one PK do not collapse the median. It is the default
   for `compute_coverage`; an explicit `gap_min_m` still pins the old
   behaviour. The status line marks an inferred threshold as `auto`.
4. **PK placemarks without a photo.** `SpatialCalculator.pk_placemarks()` lists
   the parseable, non-landmark stations; coverage flags those with no photo
   within `pk_tolerance_m` as `missing_pks`. This is the most actionable output
   for a delivery whose unit of work *is* the PK post.
5. **Surfaced everywhere the operator looks**: sidebar banner (raised to
   warning when there are interior holes or missing PKs), status bar, log,
   CSV export (coverage summary + gap kinds + `pk_sin_foto` section) and
   GeoJSON (`gap_kind` on gap lines, `missing_pk` point features, coverage
   properties).

## Consequences

- On the reference delivery the report goes from *190 gaps / 5 % coverage* to
  **1 real gap** (PK-427+952 → PK-428+356, 404 m ≈ 2.7× the flight's cadence),
  65 % of trace within 50 m of a photo, and **110 of 315 PK posts with no
  photo** — three numbers an operator can act on.
- Positive: no new dependencies; all logic stays in the pure `core.coverage`
  module and is unit-tested without Qt.
- Trade-off: a deliberately partial flight (one zone of a long corridor) now
  shows a low coverage ratio and a long missing-PK list. That is accurate, and
  the banner only warns — nothing blocks the rename.
- Trade-off: the adaptive threshold means the same job can report a different
  `gap_min_m` between runs if the photo set changes. The value is always shown
  next to the gap count, and CSV/GeoJSON record it.
- Risk: `pk_tolerance_m` is a constant (50 m). Corridors with a different post
  spacing may want it configurable; deferred until a job needs it.
