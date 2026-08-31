# Renombrador PKS — Lista de tareas (AgentsOrchestrator)

**Spec:** `project-specs/renombrador-pks-setup.md`  
**QA gate:** `python -m pytest tests/ -q --tb=short` (QT_QPA_PLATFORM=offscreen)  
**Última integración:** 326 tests + 20 subtests — PASS (fase 7 / T36)

---

### [x] T1 — Copia de seguridad por defecto y umbral 30 m
- `create_backup: true`, `threshold: 30.0`, spinner máx. 250 m
- **Agente:** ui-designer

### [x] T35 — Visor: capas base y solape del buscador
- CARTO exige API key desde 2026 (responde 200 con la tesela marcada); por defecto
  ahora ortofoto PNOA/IGN, y `maxNativeZoom` en las cuatro capas
- Buscador convertido en control de Leaflet: sin solape (medido: 186 px) ni robo de clics
- Verificado en navegador real con Leaflet incrustado: teselas de `www.ign.es`,
  `elementFromPoint` sobre el control devuelve la etiqueta de capa
- **Agente:** ui-designer + reality-checker + code-reviewer

### [x] T2 — Restaurar sesión con KML
- `_restore_last_session` recarga carpeta y `spatial_calc.load_kml`
- **Agente:** senior-developer

### [x] T3 — Auto-umbral bajo control de worker global
- `_on_auto_threshold` usa `_start_worker` (cancelación Esc)
- **Agente:** senior-developer

### [x] T4 — Diálogo de conflictos en renombrado
- Bloqueo si solo hay conflictos; advertencia explícita si hay omitidos
- **Agente:** ui-designer

### [x] T5 — KML obligatorio para analizar
- Validar en `_on_analyze` antes de lanzar worker
- **Agente:** code-reviewer

### [x] T6 — Aislar workers de análisis (thread-safety)
- `AnalysisWorker` con instancias locales de core; sincronizar KML en UI al terminar
- **Agente:** software-architect

### [x] T7 — Renombrado secuencial en disco
- `process_images` usa un solo hilo para operaciones FS
- **Agente:** software-architect

### [x] T8 — Test integración `process_images`
- Carpeta temporal, JPEG mínimo, verificar rename + backup
- **Agente:** code-reviewer

### [x] T9 — Accesibilidad vista previa
- Columna «Incluir», `AccessibleTextRole` en estado
- **Agente:** accessibility-auditor

### [x] T10 — Integración final
- Suite completa (83 tests) — **PASS**
- **Agente:** testing-reality-checker

---

### [x] T11 — Índice espacial para nearest-PK
- `SpatialCalculator` usa `shapely.strtree.STRtree` sobre el marco métrico local; O(log n) en vez de escaneo lineal + haversine
- **Agente:** performance-benchmarker

### [x] T12 — Detección de duplicados por rejilla
- `mark_duplicates` bucketiza por celda (tolerancia GPS) + fecha; ~O(n) en vez de O(n·kept)
- **Agente:** performance-benchmarker

### [x] T13 — Extracción de sesión/recientes fuera de `MainWindow`
- `session_store.py` (`SessionStore`) y `recents.py` (`push_recent`) sin dependencia de Qt
- **Agente:** software-architect

### [x] T14 — Logging consistente en `SpatialCalculator`
- `except: pass` silenciosos sustituidos por logging debug/warning/info
- **Agente:** code-reviewer

### [x] T15 — Tests para módulos extraídos
- `test_session_store.py`, `test_recents.py`, tests adicionales de índice espacial y duplicados en borde de rejilla
- **Agente:** code-reviewer

### [x] T16 — Integración final (fase 2)
- Suite completa (100 tests, 17 subtests) — **PASS**
- **Agente:** testing-reality-checker

---

### [x] T17 — Referenciación lineal calibrada (cadena oficial)
- Interpolación piecewise entre anclas PK del KML (slack chainage) en `SpatialCalculator.calculate_pk`
- Distancia de umbral = perpendicular a la traza (`corridor_distance`), no al PK más cercano; landmarks conservan distancia euclídea
- Nombres de foto usan PK interpolado (`10+500`) en vez de snap al placemark; landmarks sin cambio
- Informe de cobertura / huecos de cadena (`src/core/coverage.py`) en barra de estado + sección en CSV
- Export GeoJSON (`Ctrl+Shift+E`) con fotos + huecos proyectados sobre la traza; ADR-005
- **Agente:** product-innovation + senior-developer

---

## Pendiente (fase 4, no bloqueante)

- Más tests de UI Qt de `MainWindow` (diálogos de conflicto, undo, importación de vídeo)
- Perfilado de memoria en lotes de >5000 fotos
- Modo opcional «snap a PK más cercano» para equipos que prefieran el comportamiento legacy de nombres
- `pk_tolerance_m` configurable para corredores con hitos cada 250 m o 1 km

---

## Fase 6 — Fiabilidad del undo y saneado de dependencias

### [x] T28 — Undo de lotes encadenados (bug confirmado)
- Reproducido: `A→B` + `C→A` dejaba un fichero sin restaurar (`ok=1, conflict=1`)
- `undo_rename_operations` reproduce en orden inverso; los buckets de basenames
  duplicados se consumen también en inverso para conservar el emparejamiento legacy
- Regresión en los dos canales: `test_rename_report.py` y `test_undo_history.py`
- **Agente:** code-reviewer

### [x] T29 — Eliminar la rama muerta de `fastkml`
- Fallaba en todas las cargas desde fastkml 1.x y consumía el 82 % de `load_kml`
- Dependencia fuera de requirements, `.spec`, instalador y README
- `test_kml_dialects.py` fija lo que esa rama decía cubrir
- **Agente:** performance-benchmarker + reality-checker

### [x] T30 — Contrato de dependencias
- `shapely>=2.0` y `piexif>=1.1.3` con la razón inline
- `test_dependency_contract.py`: las suposiciones sobre terceros fallan con nombre
- **Agente:** software-architect

### [x] T31 — Fotogramas SRT como evidencia, no como objetivo de renombrado
- Reproducido: 4 cues → vista previa con 1 entrada de plan y `{ok: 0, errors: 4}` en F7,
  renombrando el propio `.SRT`
- `PhotoItem.virtual` + ruta sintética única; excluidos del plan, contados en cobertura
- `SessionStore` deja de descartarlos por no existir en disco (regresión detectada por test)
- **Agente:** senior-developer + reality-checker

### [x] T32 — `config.json` fuera del control de versiones
- Estaba en `.gitignore` pero versionado desde el commit inicial: publicaba rutas UNC
  internas y nombres de cliente
- Desversionado; `ConfigManager` ya lo regenera desde `config.example.json`
- **Agente:** code-reviewer

### [x] T33 — Entrada no confiable del KML en el visor (ADR-010)
- Reproducido: `</script>` en un placemark rompe el bloque de script; `<img onerror>`
  ejecuta al renderizar el popup; una comilla escapa del `onclick` de la búsqueda
- Payload escapado + `esc()` en la plantilla + lista de búsqueda construida con DOM
- Verificado en navegador real: título intacto, cero `img[onerror]`
- **Agente:** security-auditor

### [x] T34 — La barra de estado ya no dimensiona la ventana
- Detectado ejecutando la app real: tras analizar 238 fotos la ventana pasaba de
  1400 a 1932 px de ancho y su mínimo quedaba en 1932 (no se podía encoger)
- Causa: `QLabel` de estado sin elidir pidiendo 3576 px al layout
- `ElidingLabel` (política horizontal `Ignored` + tooltip con el texto completo)
- **Agente:** ui-designer

---

### [x] T17b — Auto-umbral vía worker (corregir drift T3)
- `_on_auto_threshold` usa `AutoThresholdWorker` + `WorkerController` (Esc cancela, UI no bloquea)
- **Agente:** senior-developer

### [x] T18 — `WorkerController` extraído de `MainWindow`
- `src/ui_qt/worker_controller.py`: start / cancel / clear / busy gate
- Autosave pausado mientras hay worker activo
- **Agente:** software-architect

### [x] T19 — Recuperación operador tras renombrado parcial
- `classify_rename_outcome` + diálogo con «Deshacer ahora» / «Abrir carpeta»
- **Agente:** ui-designer + support-responder

### [x] T20 — RenameWorker con core aislado
- F7 instancia `RenamerLogic` dedicado (misma asimetría que AnalysisWorker)
- **Agente:** software-architect

### [x] T21 — Tests fase 3
- `test_worker_controller.py`, `test_rename_outcome.py`
- **Agente:** code-reviewer

---

## Fase 5 — Rendimiento del análisis y QA de cobertura real

### [x] T22 — Índice de sidecars por carpeta (O(n²) → O(n))
- `SidecarIndex` + `collect_analysis_tree` reutilizan el `os.walk` del análisis
- `process_images` deriva los sidecars de su propio plan (sin re-escanear el directorio)
- Benchmark: `scripts/bench_analysis_hotpath.py` (2000 fotos: 6,8 s → 0,015 s)
- **Agente:** performance-benchmarker

### [x] T23 — Partición landmark/PK cacheada en `SpatialCalculator`
- `_ensure_landmark_partition` + `STRtree` solo de PKs para el fallback
- Invalidación en `set_landmark_groups` / `add_named_points` / `_reset_state`
- **Agente:** performance-benchmarker

### [x] T24 — Cobertura relativa a la traza
- `axis_pk_extent()` / `pk_placemarks()`; huecos `inicio` / `interior` / `final`
- % de cobertura por huella (±50 m) y lista de PK sin foto
- **Agente:** product-innovation

### [x] T25 — Umbral de hueco adaptativo
- `suggest_gap_min()` = max(100 m, 2,5 × espaciado mediano); ignora ráfagas < 5 m
- Validado con entrega real: 190 huecos ruidosos → 1 hueco real de 404 m
- **Agente:** reality-checker

### [x] T26 — Superficie de operador
- Banner lateral, barra de estado, log, CSV (resumen + `pk_sin_foto`) y GeoJSON (`missing_pk`)
- **Agente:** ui-designer

### [x] T27 — Tests fase 5
- `test_sidecar_index.py`, `test_landmark_partition.py`, `test_coverage_trace.py`,
  `test_main_window_coverage_ui.py` (primer test real de `MainWindow`),
  `test_logging_console_encoding.py` — 246 tests PASS
- **Agente:** code-reviewer

---

## Fase 7 — Selector de obra

### [x] T36 — Un proyecto por corredor (ADR-011)
- `core/projects.py` (sin Qt): `Project`, `ProjectStore`, detección de raíz por ruta
  y migración desde la config global
- Selector en el panel + «Guardar ajustes como obra…»; la carpeta elige la obra
- Aviso antes de F5 si la carpeta no es de la obra activa (el fallo silencioso que
  creaba `VERTEDEROS/Caliche-Palomares` en la entrega de otro cliente)
- Verificado con la config real: nombre, ámbito, traza, umbral, sufijo, 5 vertederos,
  el grupo Caliche-Palomares y los 29 viaductos migran intactos
- **Agente:** software-architect + ui-designer

### Pendiente de decidir
- Los ficheros de obra son locales: si aparece un segundo operador, valorar moverlos
  al servidor (implicaría escribir en carpetas de cliente y depender de la red)
