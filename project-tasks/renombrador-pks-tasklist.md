# Renombrador PKS — Lista de tareas (AgentsOrchestrator)

**Spec:** `project-specs/renombrador-pks-setup.md`  
**QA gate:** `python -m pytest tests/ -q --tb=short` (QT_QPA_PLATFORM=offscreen)  
**Última integración:** 246 tests + 19 subtests — PASS (fase 5 / T22–T27)

---

### [x] T1 — Copia de seguridad por defecto y umbral 30 m
- `create_backup: true`, `threshold: 30.0`, spinner máx. 250 m
- **Agente:** ui-designer + code-reviewer

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
