# ADR-015: Recognise each KML by its content, and let the KML decide the folders

## Status

Accepted — 2026-10-02

## Context

Every client folder holds several KML and only one is the trace. On the real
share (23 files) they are four different kinds, and the names do not say which:

| Kind | What is inside | Example |
|---|---|---|
| trace | hundreds of placemarks named like a chainage post | `Puntos para script.kml` (180 PK) |
| landmarks | a few named points that are *not* posts | `Vertederos.kml` (`TP01`) |
| survey | polygons, or 123 401 `LineString` with a few posts in them | `66835 Riquelme_Torre Pacheco.kml`, 27 MB |
| empty | 0 bytes | `Ortofoto.kml`, `MDS.kml` |

The operator picked the trace by hand. Picking the wrong one put the whole
delivery at PK-0+000 without a word (v3.9.2 added a warning *after* the
mistake).

Separately, the program created `OTROS` / `VIADUCTOS` / `VERTEDEROS` in every
job. That is Torre Pacheco's convention and real deliveries there contain it,
but Pulpí-Vera is delivered as `Enlace/Traza` and Lorca-Pulpí differently
again, and neither KML defines landfills or viaducts. The classic tree there is
three empty folders nobody asked for, in a client's delivery.

## Decision

`core/kml_profile.py` (Qt-free) classifies a KML by what it contains and
`discover_kmls` / `recommend` choose the trace and the landmark files around a
delivery folder. The window fills them in when a folder is chosen with no KML,
and "Detectar KML de la obra" does it on demand and says what it found and what
it ignored, with the reason.

- **Counting is not enough, so a trace is verified.** The survey file has 370
  PK-named points and would be picked on count alone. A candidate is loaded
  into a `SpatialCalculator` and kept only if it reproduces its own anchors
  (`calibration_residual_m`, the v3.9.2 check): the real trace scores 0.00 m and
  the survey file 18 553 m. No second heuristic to keep in step.
- **An axis inferred from the posts is "unverified", not "ok".** It passes
  through them by construction; claiming 0.00 m would claim a check that did
  not happen.
- **The search is shallow and bounded.** The delivery folder, its ancestors up
  to the job root (`…/CLIENTES/<obra>`), and a `kml/` sub-folder. Never the
  photos: a delivery is thousands of JPEG over SMB. It never climbs past the job
  root, so another client's KML cannot be offered.
- **It runs in a worker.** Verifying the 27 MB file costs 3–4.5 s over SMB;
  every other file is 50–200 ms.
- **The folder tree follows the job (`work_roots`).** `VERTEDEROS` exists if the
  KML defines landmarks, `VIADUCTOS` if viaduct PK are configured, and `OTROS`
  only accompanies one of those. Off by default so existing callers keep the
  classic tree; the window turns it on. Photos that match nothing stay in the job
  root, where `resolve_output_dir` already sends them.
- **The scaffold moves after the analysis.** It used to run in F5 *before*
  analysing, when the calculator could still hold the previous job's KML, which
  would give the wrong plan. `process_images` creates each photo's destination as
  it goes, so the scaffold was only ever cosmetic.
- **Discrepancies are reported, not silently fixed.** The landfills a trace KML
  defines that the job has not registered are listed. Registering them would
  change where photos go, which is the operator's call.

## Consequences

- Choosing the trace stops being a thing the operator can get wrong, and the
  v3.9.2 warning now points at the button instead of leaving them to guess.
- Measured on all 23 real files: 23/23 classified correctly; Pulpí-Vera and
  Lorca-Pulpí would get no work folders, Torre Pacheco the full set.
- Trade-off: a trace with no landmarks and no viaducts gets no `OTROS`, so a
  photo that "belongs" nowhere lands in the job root rather than in a folder
  that never existed there. That matches what those jobs already deliver.
- Trade-off: the 27 MB survey file makes the first recognition on Torre Pacheco
  take a few seconds. It runs off the UI thread, and is only paid when a folder
  is chosen with no KML or the button is pressed.
- Not done: viaduct PK are still typed by hand. No real KML has a folder of them
  to read from, so supporting one would be guessing at a convention.
