# ADR-010: KML names and file paths are untrusted input in the map

## Status

Accepted — 2026-08-28

## Context

`MapManager.build_map_html` injects the analysed photos, the trace and the KML
placemarks into `src/assets/map_template.html`, and the result is opened with
`webbrowser.open` (external browser, `file://`) or loaded into the embedded
`QWebEngineView`. Two of the injected fields come from outside the program:

- **Placemark names**, from the client's KML/KMZ. XML text decodes entities, so
  a name really can contain `</script>` or `<img …>`.
- **File names and paths**, from the operator's disk.

Both reached the document unescaped, at two different layers:

1. **Parse time.** `json.dumps` does not escape `<`, so a placemark named
   ``PK-1</script><script>…</script>`` closed the map's script block and the
   remainder of the payload was parsed as markup. Verified against the real
   generator before the fix.
2. **Render time.** The template builds popup markup by string concatenation
   (`'…<h4>' + photo.name + '</h4>…'`, `'…Hito:</b> ' + pt.name + '…'`) and
   built the search list with an inline
   `onclick="focusPhotoByName('" + m.name + "')"`. Leaflet renders popup
   content lazily, so even a payload-safe name like `<img src=x onerror=…>`
   would execute when the operator clicked the marker, and a name containing an
   apostrophe escaped the `onclick` attribute.

Escaping only the JSON would have closed the first hole while leaving the
second — and made the code look safe.

## Decision

1. `_json_for_script` escapes `<`, `>`, `&` and U+2028/U+2029 as `\uXXXX`
   before the payload is embedded. Those characters only occur inside JSON
   strings, so the decoded values are unchanged.
2. The template gains an `esc()` helper and applies it to every untrusted field
   it concatenates into HTML: `pt.name`, `photo.name`, `photo.pk`,
   `photo.view_label` and the image `src` / fullscreen handler.
3. The search results are built with DOM APIs (`textContent` plus an
   `addEventListener`), so no name is interpolated into an attribute at all.

## Consequences

- Verified in a real browser on a generated map whose placemark name carried
  `<img src=x onerror="document.title='INYECTADO'">`: the page renders, the
  title is untouched and there are zero `img[onerror]` nodes. (The preview pane
  serves the page as `data:` and blocks the vendored `file://` Leaflet, so the
  lazy popup path could not be exercised there; `test_map_component.py` pins it
  structurally instead — the test fails if anyone reintroduces a raw
  `+ photo.name +` or the inline `onclick`.)
- Escaping is transparent: names still display exactly as written in the KML.
- Rule for future work: **anything that originates in a KML or in a filename is
  untrusted at every sink**, not just at the one being touched. The CSV export
  is the remaining sink of the same class (Excel formula injection on a cell
  starting with `=`, `+` or `@`); it is left alone deliberately, because
  prefixing text with `'` would corrupt a report operators read by hand, and
  the field values are authored by the same team that opens the file.
