# ADR-005: Calibrated linear referencing and corridor distance

## Status

Accepted — 2026-08-27

## Context

The renamer already computed:

- perpendicular distance to the project axis (`distance_to_axis`);
- geometric chainage along the axis (`project` + a single median `pk_offset`).

In practice, analysis and naming still behaved like a **nearest PK placemark** tool:

1. Threshold filtering used Euclidean distance to the closest named point. A photo sitting on the centreline halfway between sparse kilometre posts (e.g. every 1 km) could be hundreds of metres from the nearest placemark and fall *outside* a 30 m corridor buffer — even though it is on the road.
2. Filenames snapped to the nearest placemark label (`PK-10+000`) instead of the continuous official station (`PK-10+500`).
3. A single median offset cannot absorb **slack chainage** (2D centreline length ≠ posted PK), which is a known issue in corridor surveying tools such as Riley Paul's Chainage Photo Renamer and linear-referencing workflows (QChainage, shapely `project`/`interpolate`, Whitebox LRS).

Industry corridor practice separates two questions:

- *Is the photo inside the corridor?* → perpendicular distance to the centreline.
- *Where along the road is it?* → calibrated measure / official PK.

## Decision

1. **`corridor_distance`**: landmarks keep Euclidean distance to the placemark; all other photos use perpendicular distance to the axis when a centreline exists.
2. **Calibrated `calculate_pk`**: build `(geom_dist, official_pk)` anchors from parseable PK placemarks and piecewise-interpolate (extrapolate beyond ends). Fall back to `geom_dist + pk_offset` with fewer than two anchors.
3. **Naming**: non-landmark photos use `format_pk_label(pk_value)` (`km+mmm`). Landmarks keep their configured names. Folder routing (vertederos / viaductos) still uses `nearest_name`.
4. **Coverage QA**: after preview, report chainage span and gaps ≥ 100 m in the status bar; CSV and GeoJSON export include gap records. Gap LineStrings are projected onto the real centreline in WGS84.

## Consequences

- Positive: names and thresholds match how road projects talk about PK; sparse KMLs become usable; operators see silent holes without opening GIS.
- Positive: no new dependencies (shapely linear referencing already present).
- Trade-off: teams that relied on every photo near a post sharing the exact placemark string will now see distinct interpolated stations (usually desirable). A legacy “snap to nearest” mode remains listed as optional future work.
- Risk: mis-labelled PK placemarks in the KML still poison calibration — same as before for `pk_offset`, but now locally between bad anchors.
