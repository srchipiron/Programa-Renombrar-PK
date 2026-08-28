# ADR-011: One project per corridor, selected in the app

## Status

Accepted — 2026-08-28

## Context

AEROSCAN delivers monthly surveys for three corridors, and each one carries its
own rules. Read from the production share:

| | Torre Pacheco | Pulpí-Vera | Lorca-Pulpí |
|---|---|---|---|
| Chainage | PK-18+653 → 36+400 | 500+000 → 525+700 | 400+500 → 431+834 |
| Trace | `Puntos para script.kml` | `PuntosLimpiosParaPrograma.kml` | `Tronco LAV Lorca Pulpí.kml` |
| Landfills | 5 in the trace KML + `TP-01` in `Vertederos.kml` | none | none |
| Viaduct PKs | 29, hand-typed in `config.json` | — | — |
| Delivery | root of `2026/8.Agosto` | `2026/5.Mayo/1.Editadas` | `2026/7.JULIO/Imagenes` |

All of it lived in a single global `config.json`, so switching corridor meant
editing seven fields by hand, one of them a 29-entry list.

Forgetting to switch does not fail: it fails **silently**. Torre Pacheco's
landfills sit 200 km from the Lorca-Pulpí trace, so they never capture a photo;
its viaduct PKs (`22+600`) do not exist in a 400+ km chainage, so they never
match. The run looks clean. But `ensure_work_folders` still creates that
corridor's folders in the other client's delivery — simulated in a temp
directory with the real config: `VERTEDEROS/Caliche-Palomares`, `Gregal`,
`Vertedero 1`, `Vertedero 2` inside a Lorca-Pulpí job.

The client also edits the rules between deliveries: in August they added the
landfill **TP-01** and asked for that exact folder name.

## Decision

1. **`Project`** (`core/projects.py`, Qt-free) bundles what changes per
   corridor: `root`, trace KML, landmark files, landmarks and their groups,
   viaduct PKs, thresholds and filename suffix.
2. **One JSON per corridor in a local directory** (`proyectos/`, configurable).
   *Not* inside the client folders on the share: the app must not write there,
   and the project list must not depend on the network being up. `root` is only
   ever compared against, never written to.
3. **Applying a project writes its settings into the live `AppConfig`.** The
   workers, `ensure_work_folders` and the renamer keep reading config as
   before and need no knowledge of projects.
4. **The folder picks the corridor.** The delivery tree is
   `…/CLIENTES/<obra>/<año>/<mes>/`, so choosing a folder is enough to know
   which rules apply; the deepest matching root wins. Switching corridor drops
   the current analysis — photos measured against another trace carry
   meaningless PK, routing and labels.
5. **A guard before F5**: analysing a folder outside the active corridor's root
   asks for confirmation and names both, because that is exactly the silent
   failure above.
6. **Migration**: on first run the current global settings are saved as the
   first project (named after the client folder) and made active, so the guard
   is armed from launch one instead of after the operator picks it by hand.
   Verified against the real config: name, root, trace, threshold, suffix, five
   landfills, the Caliche-Palomares group and the 29 viaduct PKs all survive.

## Consequences

- Switching corridor is a dropdown instead of seven fields, and picking a
  folder from another client now warns instead of quietly polluting it.
- Positive: a fourth corridor is a JSON file, no code change. "Guardar ajustes
  como obra…" writes one from whatever is on screen, so no editor dialog is
  needed to create it.
- Trade-off: project files live on the operator's machine, so two operators do
  not share them automatically. Putting them on the share would fix that, at
  the cost of writing into client folders and of a network dependency for the
  app to know its own projects. Revisit if a second operator appears.
- Trade-off: `AppConfig` still mirrors the active project, so editing those
  fields by hand still works — and still silently diverges from the project
  file until "Guardar ajustes como obra…" is used. The selector is the
  intended path.
- Risk: `guess_project_root` keys on a path segment named `CLIENTES`. Outside
  that tree it falls back to the parent folder, which may be too narrow; the
  operator can correct `root` in the JSON.
