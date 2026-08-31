# ADR-014: The delivery report is self-contained HTML

## Status

Accepted — 2026-08-31

## Context

The program computed everything a monthly hand-over needs — the chainage span
actually flown, the coverage against the trace, the holes, the PK posts with no
photo, and where every file was routed — and then offered it as three separate
exports (CSV, GeoJSON, map) that the operator recomposed by hand for each
delivery. The client relationship is monthly and formal (UTEs, independent
engineers), so that recomposition happened every month.

Nothing was missing from the calculations. What was missing was a document.

## Decision

`core/delivery_report.py` renders one **self-contained HTML** file: header with
the job, period and threshold; KPI row; a coverage bar; the gaps; the PK posts
with no photo; the routing breakdown; and the full index of delivered files.
`Ctrl+I`, defaulting to the job folder.

- **HTML, not PDF.** A PDF needs a rendering dependency (ReportLab, WeasyPrint)
  in a bundle that already ships 700 MB of QtWebEngine. The browser prints to
  PDF, the file opens anywhere, and it can be emailed as is. The stylesheet has
  a `@media print` block so the page breaks land between rows and the table
  headers repeat.
- **No external assets at all** — no CDN, no linked images, no scripts. A
  report that stops rendering when it leaves the machine is not a deliverable;
  the test asserts there is no `http://`, `https://` or `file://` in the output.
- **A coverage bar, drawn to scale as inline SVG.** A percentage says how much
  of the trace is covered; the bar says *where* the holes are, which is what
  decides whether anyone flies again. On the August job it shows seven red
  segments over the 18+653–36+400 span.
- **Rendered from the same data the preview shows.** The handler refreshes the
  preview before building, so the document cannot disagree with the screen.
- **Everything escaped.** Photo names come from disk and PK labels from the
  client's KML (ADR-010); the same rule applies to this sink.

## Consequences

- The monthly hand-over stops being a manual recomposition; the operator can
  also read it before sending to see what the client will see.
- Measured on the real August job (117 photos): 11 ms to build, 26 KB, 113 rows
  in the index, and the counts match the preview exactly.
- Trade-off: printing depends on the browser, so pagination varies slightly
  between Chrome and Edge. Acceptable for an annex; if a fixed layout is ever
  required, that is the moment to take on a PDF dependency.
- Trade-off: the index lists every delivered photo, so a 400-photo job produces
  a long annex. That is what an index is, and the summary sits above it.
- The threshold's provenance ("corte en el salto de distancias" vs a hand-typed
  value) is carried into the report, so a reader can tell whether the number
  was chosen by the program or by a person.
