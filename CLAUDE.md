# Renombrador PKS

Aplicación de escritorio (PySide6/Qt6, Windows) que renombra fotografía aérea de
dron según su punto kilométrico sobre la traza de una obra lineal, y la enruta a
la estructura de entrega del cliente. Usuario real: AEROSCAN, entregas mensuales
a UTEs de obra ferroviaria y de carretera.

## Comandos

```bat
python main.py                      REM arrancar la app
scripts\run_checks.bat              REM QA completa (lo que exige el CI)
python -m pytest tests/ -q          REM tests (necesita QT_QPA_PLATFORM=offscreen)
build.bat                           REM carpeta portable + ZIP + instalador
python scripts\bench_analysis_hotpath.py   REM benchmark del camino caliente
```

`QT_QPA_PLATFORM=offscreen` es obligatorio para los tests: sin él, los que
construyen `MainWindow` abren ventanas reales.

## Arquitectura

- `src/core/` — dominio **sin Qt**. Se testea sin `QApplication` y es la razón de
  que 370 tests corran en 3 s. No importes PySide6 aquí.
- `src/ui_qt/` — ventana, workers en hilos con señales Qt, diálogos. Solo cablea.
- `src/map_component.py` + `src/assets/map_template.html` — visor Leaflet offline.
- `docs/adr/` — cada decisión de peso tiene su ADR con el porqué y los contras.
  Si tomas una, añade el siguiente número.

Los workers construyen **sus propias instancias** de `SpatialCalculator` y
`RenamerLogic`: nunca compartas las del hilo de UI con un worker.

## Vocabulario del dominio

- **PK** — punto kilométrico, `km+mmm` (`22+600`). La cadena oficial se interpola
  entre las anclas del KML, no se hace *snap* al placemark más cercano (ADR-005).
- **Traza / corredor** — el `LineString` del KML. El umbral mide distancia
  **perpendicular** a él.
- **Vertedero (landmark)** — punto con nombre que no es un PK. Se detecta así:
  placemark cuyo nombre no parsea como PK. Van a `VERTEDEROS/<nombre>`.
- **Viaducto** — PK listados en la obra; van a `VIADUCTOS/`.
- **Obra (proyecto)** — un corredor con su traza, vertederos, viaductos, umbral y
  sufijo. Un JSON por obra en `proyectos/` (ADR-011).
- **Sufijo** — texto añadido al nombre, lleva el mes (`[PK]-AGO26`). Con
  `[PK]-{MES}{AA}` se resuelve desde la carpeta y deja de caducar (`core/naming.py`).
- **Vista** — `TI`/`CEN`/`TD`/`TRAZA`, deducida del gimbal DJI y del rumbo del eje.

## Trampas verificadas

- **Las rutas de escritura salen de `src/core/paths.py`**, nunca de
  `Path(__file__).parents[...]`. Instalado en `Archivos de programa` esa carpeta
  es de solo lectura (ADR-012).
- **`map_tab.py` importa `QtWebEngineWidgets` a nivel de módulo**: un build sin
  QtWebEngine no arranca, no se degrada.
- **Chromium corre con `--disable-gpu`** (evita un crash en Windows), así que el
  mapa lo pinta la CPU y cada nodo DOM cuesta. Por eso los hitos PK se dibujan en
  canvas y no como marcadores (medido: 553 nodos y 44 ms → 0 nodos y 11 ms).
- **Los nombres del KML son entrada no confiable**: vienen del cliente. Escápalos
  en cualquier sumidero (ADR-010).
- **Las distancias son bimodales** en trabajos reales: corredor + un puñado a
  kilómetros. El umbral corta en el salto, no en un percentil (ADR-013).
- **Un `.bat` con finales de línea LF no se ejecuta**: `cmd.exe` recorre el
  fichero por desplazamiento de bytes contando CRLF, y sin ellos se come los
  primeros caracteres de cada línea (`setlocal` → `ocal`). `.gitattributes` lo
  fuerza; no lo quites ni normalices los `.bat` a LF.
- **Mira el código de salida de pytest, no sólo el resumen**: un
  `QWebEngineView` creado en un test sobrevive hasta el cierre del intérprete y
  Chromium tira el proceso *después* de que todo pase en verde. Salía 139 con
  «458 passed». Por eso los tests del mapa no instancian Chromium.
- **Los tests corren con el Python del sistema**, no con `venv\`. Hoy coinciden;
  si divergen, `run_checks.bat` daría verde sobre otro entorno. El CI usa 3.12 y
  el desarrollo va con 3.14.
- **`config.json` y `proyectos/` no se versionan**: llevan rutas UNC y nombres de
  cliente. `config.example.json` sí, y de ahí se crea el primero.
- **`fastkml` se eliminó**: su única llamada fallaba en todas las cargas desde
  fastkml 1.x. El KML lo parsea `lxml` (ADR-008). No lo reintroduzcas sin motivo.

## Datos reales

Las obras viven en el recurso de red
`//dsconecta/aeroscan/.../CLIENTES/<obra>/<año>/<mes>/`. Esa estructura es la que
usa la app para deducir la obra a partir de la carpeta elegida.

**No escribas en esas carpetas** salvo que la tarea sea exactamente eso: son
entregas de cliente. Analizar (F5) ya crea `OTROS/`, `VIADUCTOS/`, `VERTEDEROS/`
y un `.pk_exif_cache.json`; tenlo en cuenta antes de lanzarlo sobre una entrega.

Las fotos son JPEG de ~14 MB sobre SMB: cualquier cosa que las lea enteras se
nota. Léelas por cabecera cuando baste (miniatura embebida, EXIF).

## Convenciones

- Cadenas de interfaz y mensajes al operador **en español**; código, docstrings y
  comentarios **en inglés**.
- Los comentarios explican el *porqué* y suelen citar la medición que lo motivó.
  Mantén ese nivel: son la memoria del proyecto.
- Los tests describen comportamiento observable, con el fallo real en el
  docstring. Si un test falla tras un cambio, decide si defendía algo real antes
  de tocarlo.
- Antes de optimizar, **mide** — con los datos reales de `//dsconecta` o con los
  benchmarks de `scripts/`. Varias "mejoras obvias" de este repo resultaron ser
  lo contrario al medirlas.

## Entregables

`Ctrl+I` genera el informe de entrega (HTML autocontenido, imprimible a PDF) a
partir de los mismos datos que muestra la vista previa. `Ctrl+E` CSV,
`Ctrl+Shift+E` GeoJSON, `F8` mapa.

## Diagnóstico

`Ctrl+Shift+D` genera un informe con versión, rutas y su accesibilidad,
dependencias, obra activa, estado del análisis y cola de los registros. Es la
primera cosa que pedir cuando alguien reporta un fallo.

La versión vive en `src/core/version.py` y solo ahí.
