# ADR-006: One directory listing per folder, one point partition per KML

## Status

Accepted — 2026-08-27

## Context

A profile of the analysis path (F5) on a job of a few thousand photos found two
quadratic hot spots that dominated everything else, including EXIF I/O:

1. **Sidecar discovery.** `find_sidecars(photo)` ran one `os.scandir` of the
   photo's directory *per photo*, so a folder of N photos performed N listings
   of N entries. Measured on a local SSD: 0.46 s for 500 photos, 1.7 s for
   1000, **6.8 s for 2000** — pure O(n²) growth, before a single byte of EXIF
   was read. Production jobs live on SMB shares (`//dsconecta/...`), where a
   directory listing costs orders of magnitude more than locally. The same
   helper was called again per file during rename (F7), on a directory that was
   simultaneously being mutated.

2. **Nearest-PK with landmarks configured.** ADR-004 introduced an `STRtree`
   for nearest-PK lookups, but the landmark layer added afterwards re-scanned
   **every** named point per photo — once to collect landmarks within the
   capture radius (with a `strip().casefold()` per point), and again in the
   "the nearest point is a far-away landmark" fallback. With landmarks always
   present in the real config, the tree's O(log n) was cancelled out by two
   O(n) sweeps per photo.

## Decision

1. **`SidecarIndex`** (`core/renamer_logic.py`) maps `directory → {stem:
   [sidecar paths]}`. `collect_analysis_tree()` fills it from the `os.walk`
   analysis already performs, so indexing companions costs **zero extra I/O**;
   unknown directories still fall back to a single on-demand `scandir`.
   `collect_analysis_image_files()` remains as a thin wrapper, and
   `find_sidecars()` stays for single-photo callers.
2. **Rename derives sidecar state from its own plan.** `process_images` no
   longer re-scans the directory after each rename: the new companion list is
   `sidecars already at the destination + the ones this job actually moved`.
   This also fixes a reporting bug — after a failed sidecar rename, companions
   that were successfully rolled back were still recorded in the undo mapping,
   so undo reported them as missing.
3. **Cached landmark/PK partition** (`core/spatial_calculator.py`). The point
   index is split once into landmark indices and PK indices, the latter getting
   its own `STRtree`. The landmark sweep iterates only landmarks (a handful),
   and the fallback is an O(log n) tree query. The partition is invalidated by
   `_rebuild_metric_axis`, `_reset_state`, `set_landmark_groups` and
   `add_named_points(mark_as_landmark=True)`, because group labels can turn
   existing names into landmarks *after* the index was built.

## Consequences

- **Measured** (`scripts/bench_analysis_hotpath.py`, local SSD):

  | Photos | Sidecars legacy | Sidecars indexed | Speed-up |
  |-------:|----------------:|-----------------:|---------:|
  | 500    | 0.46 s          | 0.004 s          | 117× |
  | 1000   | 1.71 s          | 0.008 s          | 218× |
  | 2000   | 6.78 s          | 0.015 s          | 455× |

  Nearest-PK with 400 placemarks + 5 landmarks over 4000 photos: 0.31 s → 0.14 s
  (2.3×), **identical results**. End-to-end `analyze_distance_stats` over 800
  photos with companions: 5.90 s → 0.44 s (13.4×), same items and sidecars.
- Positive: the win grows with folder size and with share latency, i.e. exactly
  where operators felt it.
- Trade-off: the sidecar index is a snapshot. Analysis only queries paths from
  the same walk, so it is always fresh there; callers that mutate a directory
  must call `SidecarIndex.forget(dir)` (or use `find_sidecars`).
- Trade-off: after rename, `item.sidecars` lists only companions the renamer
  knows about, instead of adopting any unrelated file that happens to share the
  new stem. This is deliberate — the previous behaviour could pull a stranger's
  file into the next rename batch.
