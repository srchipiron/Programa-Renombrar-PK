# 📍 Renombrador PKS - Sistema Avanzado

Aplicación de escritorio para renombrar fotografías aéreas basándose en su proximidad a puntos kilométricos (PK) definidos en archivos KML/KMZ.

## 🚀 Características Principales

### ✨ Funcionalidades Avanzadas
- **Procesamiento por Lotes**: Analiza y renombra cientos de imágenes simultáneamente
- **Cálculo Espacial Preciso**: Determina la distancia exacta de cada foto a la traza PK
- **Soporte Múltiple Formatos**: JPG, PNG, TIFF, BMP, KML, KMZ, GeoJSON, SRT
- **Vista Previa Interactiva**: Revisa los cambios antes de aplicarlos
- **Mapas Interactivos**: Visualización geográfica de los resultados
- **Informe de entrega**: HTML imprimible con cobertura, huecos e índice (`Ctrl+I`)
- **Exportación CSV**: Análisis de datos en hojas de cálculo

### 🛠️ Mejoras Técnicas
- **Arquitectura Moderna**: Separación clara de responsabilidades
- **Sistema de Eventos**: Comunicación desacoplada entre componentes
- **Logging Completo**: Registro detallado de operaciones y errores
- **Configuración Validada**: Gestión robusta de parámetros
- **Procesamiento Paralelo**: Optimización de rendimiento con hilos
- **Manejo de Errores**: Recuperación elegante de fallos

## 📋 Requisitos del Sistema

- **Python 3.10+** (probado en 3.14)
- **Windows 10/11** (recomendado)
- **4GB+ RAM**
- **Espacio en disco** para imágenes y copias de seguridad
- **Qt WebEngine** (instalado como dependencia de PySide6, requiere OpenGL disponible)

## 🛠️ Instalación

### 1. Clonar el Repositorio
```bash
git clone <repository-url>
cd "Programa Renombrar PK"
```

### 2. Crear Entorno Virtual
```bash
python -m venv venv
venv\Scripts\activate
```

### 3. Instalar Dependencias
```bash
pip install -r requirements.txt
```

### 4. Ejecutar Aplicación
```bash
python main.py
```
O simplemente haz doble clic en **`ejecutar.bat`** (o ejecuta `ejecutar.bat` en la terminal).

## 📦 Entregar el programa a otro PC

Un solo comando genera las tres formas de entrega:

```bash
build.bat
```

| Forma | Qué se envía | Requisitos en el PC destino |
|-------|--------------|------------------------------|
| **Carpeta portable** | `dist\RenombradorPKS\` completa | Ninguno: ni Python ni administrador |
| **ZIP** | `dist\RenombradorPKS-portable.zip` | Descomprimir y ejecutar `RenombradorPKS.exe` |
| **Instalador** | `dist_installer\RenombradorPKS_Setup_*.exe` | Ninguno (requiere Inno Setup **en el PC que compila**) |

El instalador solo se genera si tienes Inno Setup; si no, `build.bat` lo dice y
sigue adelante con las otras dos:

```bash
winget install JRSoftware.InnoSetup
```

### Dónde guarda sus datos

`config.json`, `proyectos\` y `logs\` se crean **junto al ejecutable** cuando esa
carpeta admite escritura — así una copia portable o un USB van completos. Si no
(por ejemplo instalado en `Archivos de programa`), pasan a
`%LOCALAPPDATA%\RenombradorPKS`. Lo resuelve `src/core/paths.py`.

### Llevarte tus obras a otro PC

Las obras son ficheros sueltos: copia `proyectos\*.json` a la carpeta de datos del
PC destino. Si no copias nada, el programa arranca limpio y crea su
`config.json` a partir de `config.example.json`.

### Tamaños medidos

| Artefacto | Tamaño |
|-----------|--------|
| Carpeta `dist\RenombradorPKS\` | 707 MB |
| `RenombradorPKS-portable.zip` | **262 MB** |

El peso viene del runtime completo de `QtWebEngine` (Chromium) que necesita el
mapa embebido. El bundle es autónomo de verdad: incluye `vcruntime140.dll`,
`msvcp140*.dll` y `QtWebEngineProcess.exe`, así que el PC destino no necesita
Python, ni el runtime de Visual C++, ni permisos de administrador.

> Una variante sin mapa embebido pesaría una fracción, pero hoy `map_tab.py`
> importa `QtWebEngineWidgets` al cargar el módulo: habría que degradar esa
> pestaña con elegancia antes de poder excluirlo.

> **Nota de empaquetado**: `tar -a -c -f x.zip` **no comprime**, solo almacena
> (medido: un DLL de 195 MB seguía ocupando 195 MB). `build.bat` usa 7-Zip si
> está disponible y `Compress-Archive` si no.

## 📦 Dependencias

- **PySide6**: Framework UI Qt6 (incluye `QtWebEngine` para el mapa embebido)
- **shapely**: Operaciones geométricas
- **Pillow**: Manipulación de imágenes
- **piexif**: Lectura de datos EXIF
- **lxml**: Procesamiento XML
- **pysrt**: Procesamiento de subtítulos

La interfaz oficial es **PySide6/Qt** (`src/ui_qt/`). Copia `config.example.json`
a `config.json` para tus rutas locales (ese archivo no se versiona).

## 🎯 Uso Rápido

### Paso 1: Configurar Archivos
1. **Carpeta de Imágenes**: Selecciona la carpeta con tus fotos aéreas
2. **Archivo KML/KMZ**: Carga el archivo con los puntos PK del proyecto
3. **Ajustar Parámetros**: Configura umbral de distancia y sufijo de nombres

### Paso 2: Analizar Imágenes
1. Haz clic en **"Analizar Imágenes"**
2. El sistema procesará todas las imágenes extrayendo:
   - Coordenadas GPS de datos EXIF
   - Distancia a la traza PK
   - Punto kilométrico más cercano
3. Revisa los resultados en la pestaña **"Vista Previa"**

### Paso 3: Procesar Cambios
1. Verifica los nombres sugeridos en la vista previa
2. Configura opciones adicionales:
   - **Crear copia de seguridad**: Guarda originales antes de renombrar
   - **Sufijo**: Texto añadido a todos los nombres
3. Haz clic en **"Procesar Cambios"** para aplicar los renombrados

## 🔧 Configuración Avanzada

### Parámetros Principales
- **Umbral (m)**: Distancia máxima para considerar imagen "dentro"
- **Sufijo**: Texto añadido al nombre (ej: `[PK]-ABR24`)
- **Workers**: Número de hilos para procesamiento paralelo
- **Backup**: Crear copias de seguridad automáticas

### Cálculo Automático de Umbral
El sistema puede calcular automáticamente el umbral óptimo basado en:
- Distribución estadística de distancias
- Desviación estándar de las mediciones
- Percentiles de la muestra

## 📊 Funciones Adicionales

### Exportación CSV
Exporta resultados detallados incluyendo:
- Nombres originales y nuevos
- Coordenadas GPS exactas
- Distancias a PK
- Estados (dentro/fuera)
- Fechas y horas de captura

### Generación de Mapas
Crea mapas interactivos que muestran:
- Ubicación de todas las imágenes
- Trazado PK del proyecto
- Puntos dentro/fuera del umbral
- Miniaturas de imágenes al hacer clic

### Soporte para Video
Procesa subtítulos SRT de drones DJI/Autel:
- Extrae coordenadas GPS de subtítulos
- Genera "fotogramas virtuales" para análisis
- Integra con flujo de trabajo principal

## 🏗️ Arquitectura del Sistema

### Estructura de Directorios
```
src/
├── core/                      # Lógica de negocio (sin dependencias de UI)
│   ├── config.py              # Configuración persistente (incluye tema)
│   ├── coverage.py            # QA de cobertura: huecos, % de traza y PK sin foto
│   ├── logging_config.py      # Configuración de logging
│   ├── models.py              # Modelos de datos
│   ├── renamer_logic.py       # Análisis, vista previa, renombrado y undo CSV
│   ├── spatial_calculator.py  # Cálculos espaciales
│   └── video_extractor.py     # Extracción de fotogramas virtuales (SRT)
├── ui_qt/                     # Interfaz PySide6/Qt
│   ├── app.py                 # Entry point (QApplication + tema + logging)
│   ├── main_window.py         # QMainWindow con sidebar + tabs + status
│   ├── sidebar.py             # Panel lateral con selectores y acciones
│   ├── preview_tab.py         # Tabla ordenable/filtrable + miniatura
│   ├── map_tab.py             # Mapa embebido con QWebEngineView
│   ├── log_tab.py             # Pestaña de registro del logger real
│   ├── help_tab.py            # Ayuda en QTextBrowser
│   ├── workers.py             # Workers en hilo (análisis, rename, undo…)
│   ├── undo_history.py        # Historial SQLite de renombrados
│   ├── undo_dialog.py         # Diálogo para revertir operaciones pasadas
│   ├── log_handler.py         # logging.Handler que emite señales Qt
│   ├── session_store.py       # Autoguardado/restauración de sesión (sin Qt, testeable)
│   ├── recents.py             # Helper puro para listas MRU (carpetas/KML recientes)
│   └── theme.py               # QSS claro/oscuro con toggle
└── map_component.py           # Generador HTML del mapa interactivo
```

Copia `config.example.json` a `config.json` en el primer arranque (el archivo local no se versiona).

### Patrones de Diseño
- **Separación core / UI**: `RenamerLogic` + `SpatialCalculator` sin PySide6
- **Señales Qt + workers**: operaciones largas fuera del hilo de interfaz
- **Historial de undo**: SQLite para lotes recientes; CSV (`reporte_renombrado.csv`) como respaldo
- **Thread-safe UI**: workers en hilos aparte + entrega vía signals
- **Índice espacial (STRtree)**: búsqueda del PK más cercano en O(log n) en vez de escanear todos los puntos por foto
- **Lógica de `MainWindow` extraída**: sesión (`session_store.py`) y recientes (`recents.py`) son módulos puros y testeables sin Qt

Ver `docs/adr/` para el detalle de cada decisión (incluye ADR-004 sobre el índice espacial y la extracción de sesión/recientes).

## 🔍 Solución de Problemas

### Errores Comunes

#### "No se encontraron imágenes válidas"
- **Causa**: La carpeta no contiene imágenes con datos EXIF GPS
- **Solución**: Verifica que las imágenes tengan coordenadas GPS

#### "Error en archivo KML"
- **Causa**: El KML/KMZ no contiene puntos o líneas válidas
- **Solución**: Valida el archivo en Google Earth antes de cargar

#### "Sin permisos para renombrar"
- **Causa**: Los archivos están en uso o protegidos
- **Solución**: Cierra aplicaciones que puedan estar usando las imágenes

### Rendimiento
- **Para muchos archivos**: Aumenta el número de workers en configuración
- **Imágenes de alta resolución**: El procesamiento puede ser más lento
- **Disco lento**: Considera usar SSD para mejor rendimiento

## 🧪 Testing

### Ejecutar Tests
```bash
python -m pytest tests/ -v
```

### Cobertura de Tests
```bash
python -m pytest tests/ --cov=src --cov-report=html
```

## 📝 Registro de Cambios

### v3.9.2 - El KML equivocado deja de pasar desapercibido
- 🚨 **Aviso si la traza no es de fiar.** Elegir el KML que no lleva traza hacía que
  *todos* los PK salieran a 0 sin que nada lo dijera; y peor, un KML cuya traza no
  recorre las anclas (el levantamiento del cliente, con 123 401 `LineString`, del que
  se toma el primero) da cifras con pinta de PK que no lo son. Ahora se le pregunta a
  cada ancla por su propio PK: **0,00 m** en el KML de traza real, **18 553 m** en el
  otro. Se avisa al operador y consta en el diagnóstico
- 🤐 Cuando el eje se **deduce** de las propias anclas, el chequeo pasa por ellas por
  construcción: en ese caso dice «sin juicio» en vez de un 0,00 m que no verifica nada
- 🪟 **Nombres de vertedero del KML contra el sistema de ficheros de Windows.** `TP:01`
  hacía que `os.makedirs` lanzara `WinError 267` **fuera** del `try` de cada foto, y se
  llevaba por delante el lote entero. Se sanean los segmentos de carpeta con la misma
  regla que los nombres de fichero (ADR-010), se quitan espacios y puntos finales que
  Windows elimina en silencio, y se escapan los nombres reservados (`NUL`, `CON`…)
- 🔡 **Renombrar `.JPG` a `.jpg` se omitía como si fuera una colisión.** Windows no
  distingue mayúsculas, así que el destino «ya existía»: era el propio fichero. La
  comparación pasa a ser por identidad de fichero, en el renombrado y en el diálogo de
  confirmación de F7
- 🧱 Una carpeta imposible cuesta **una foto**, no la entrega: `makedirs` va dentro del
  `try` de cada trabajo, y el andamiaje de `VERTEDEROS/` no aborta por una subcarpeta
- 🩹 **`scripts\run_checks.bat` no llegaba a ejecutarse**: estaba guardado con finales
  de línea LF y `cmd.exe` se comía los primeros caracteres de cada línea (`setlocal`
  llegaba como `ocal`). Convertidos a CRLF los cuatro `.bat` afectados —incluido
  `ejecutar.bat`— y añadido `.gitattributes` para que un clon nuevo no lo repita
- 💥 **La suite salía con código 139 pese a los 458 en verde**: un `QWebEngineView`
  creado en un test no se destruye nunca dentro de un bucle de eventos, y Chromium se
  llevaba el proceso al cerrar. Ese test ya no instancia Chromium: lo que comprueba es
  el ciclo del fichero temporal, no el navegador. `run_checks.bat` pasa entero
- 🧪 458 tests (antes 424) · verificado sobre 23 KML y 9 076 fotos reales

### v3.9.1 - Repaso de código: hilos, temporales y un solo lector de miniaturas
- 🧵 **`QPixmap` se creaba en el hilo de trabajo**, que Qt prohíbe: los lectores de
  miniaturas devuelven `QImage` y la conversión ocurre en el slot de la interfaz
- 🕳️ **Petición de miniatura perdida**: si una selección caía entre el «ya no hay
  trabajo» del hilo y su muerte, nadie la atendía y el panel seguía enseñando la foto
  anterior. La retirada del hilo se decide ahora bajo el cerrojo
- 🗺️ **El mapa dejaba un HTML temporal por render** (6 huérfanos encontrados, y ahora
  ~2 MB cada uno con las miniaturas embebidas). Se borra el anterior en cada render y
  el último al cerrar la aplicación
- 🖼️ **Un solo lector de miniaturas** (`core/images.py`): el mapa y la vista previa
  tenían una copia cada uno y ya habían divergido — el mapa usaba la API pública
  `getexif()` y la vista previa la privada `_getexif()`, sólo para JPEG, así que **los
  PNG y TIFF nunca se rotaban**. Un test lo vigila ahora en todo `src/`
- 💣 **Límite de píxeles explícito y finito**: las entregas reales son de 12288×8192
  (100,7 Mpx), por encima del aviso de Pillow. Funcionaba sólo porque `map_component`
  anulaba el límite global al importarse; ahora se fija una vez, con motivo escrito, y
  un fallo de lectura se registra en vez de desaparecer
- 🔗 `render_points` no tenía **ningún** test: una indentación había metido la creación
  del temporal dentro del `except`, y los 405 tests pasaban igual
- 🧹 Bandera `_running` muerta y dos importaciones sin usar
- 🏷️ La versión de `version.py` se había quedado en 3.8.0 con el README ya en v3.9; un
  test ata ahora versión, README e instalador
- 🧪 418 tests (antes 399)

### v3.9 - Informe de entrega
- 📄 **`Ctrl+I` genera el informe de la entrega**: un HTML autocontenido con la obra, el
  periodo, el umbral aplicado y de dónde salió, los indicadores, **una barra de cobertura
  a escala** que sitúa cada hueco, la tabla de huecos, los PK sin fotografía, el reparto
  por carpeta y el índice completo de la entrega
- 🖨️ Sin dependencias nuevas: se imprime a PDF desde el navegador (`Ctrl+P`) y tiene
  estilos de impresión para que los cortes de página caigan bien
- 📮 **Nada externo**: ni CDN, ni imágenes enlazadas, ni scripts. Un informe que deja de
  verse al salir del equipo no es un entregable
- 🧪 399 tests (antes 386) · ADR-014

### v3.8 - Versión visible, diagnóstico enviable y sufijo del mes automático
- 🖼️ **El popup del mapa deja de cargar el original**: mostraba el JPEG de 10-14 MB, que
  Chromium (sin GPU) tenía que descodificar en cada clic. Ahora enseña la miniatura que
  la propia cámara embebe (~14 KB) y el original queda detrás del clic de ampliar.
  Extraerlas en paralelo cuesta **0,5 s** para las 117 fotos reales sobre red (117/117)
- 📅 **El sufijo deja de caducar**: `[PK]-{MES}{AA}` se resuelve con la carpeta de la
  entrega (`2026/8.Agosto` → `[PK]-AGO26`). La obra guarda una plantilla que sirve todos
  los meses en vez de un literal que hay que cambiar — y que se olvida: en Pulpí-Vera la
  carpeta `5.Mayo` contiene ficheros `ABR26`. Un sufijo literal sigue funcionando igual,
  y un token que no se puede resolver se deja **visible** en vez de inventarse un mes
- 🔖 **Versión única** en `src/core/version.py`: sale en el título de la ventana, en la
  Ayuda, en el log de arranque y en el instalador (antes solo existía un `2026.1.0`
  suelto dentro de `installer.iss`, que podía discrepar del build)
- 🩺 **Generar diagnóstico** (`Ctrl+Shift+D`, menú Ayuda): un único fichero con versión,
  si corre empaquetado o desde código, Python/Qt, rutas y **si cada una es accesible**,
  versiones de dependencias, obra activa, configuración, estado del análisis, cobertura
  y las últimas líneas del registro. Funciona aunque no haya análisis o la traza no
  responda — un diagnóstico que solo sirve con la app sana no sirve
- 🧪 370 tests (antes 360)

### v3.7 - Umbral automático por salto de distancias
- 🎯 **El umbral se corta en el salto**, no en un percentil. Las entregas de corredor son
  bimodales: fotos sobre la traza y unas pocas en otro sitio. Medido en dos trabajos
  reales, el salto es inconfundible (10,8→44,6 m y 23,9→112 m) y entre los dos grupos
  cualquier umbral da el mismo resultado
- 🎯 **Deja de hacer falta ajustar `iqr_multiplier`**: con 1,5 y con 3,0 sale el mismo
  umbral y el mismo conjunto de fotos. Con el valor por defecto anterior se perdían
  1 y 4 fotos de corredor en esos mismos trabajos
- 💬 **Explica el porqué**: el diálogo indica el salto detectado, cuántas fotos quedan
  por debajo y que mover el umbral dentro del salto no cambia nada
- 🔁 Las distribuciones continuas no cambian: sin salto dominante se usan los percentiles
  de siempre
- 🧪 360 tests
- 📄 ADR-013

### v3.6 - Rendimiento del visor y de las miniaturas
- 🗺️ **Hitos PK en canvas**: dejaban ~300 nodos DOM en el mapa a cualquier zoom, que
  Leaflet recolocaba en cada arrastre. Medido con el Leaflet real y volumen real
  (315 hitos + 238 fotos): **553 nodos → 0**, y **44 ms → 11 ms** por tanda de
  movimientos (**4×**). Cuenta doble porque la app corre Chromium con la GPU
  desactivada y lo pinta todo la CPU
- 🐛 **El mapa ya no puede quedarse en blanco** si la vista se crea con tamaño 0:
  se revalida el tamaño al cargar y al redimensionar
- 🖼️ **Miniatura instantánea**: se muestra la vista previa que la cámara embebe en el
  fichero (**123 ms → 17 ms** para ver algo) y se sustituye por la de calidad al llegar
- 🖼️ **Caché LRU de miniaturas**: volver a una foto ya vista es instantáneo, antes
  costaba otros 123 ms
- 🖼️ Para la miniatura embebida se leen **128 KB de cabecera** en vez de los 14 MB del
  fichero: sobre recursos de red es 100× menos tráfico
- 🧪 351 tests (antes 341)

### v3.5 - Selector de obra
- 🏗️ **Cada obra con su lógica**: traza, vertederos, viaductos, umbral y sufijo dejan de
  ser globales. Un JSON por obra en `proyectos/` y un desplegable en el panel
- 🔎 **La carpeta elige la obra**: el árbol de entrega ya dice de qué corredor es
  (`…/CLIENTES/<obra>/<año>/<mes>/`), así que al elegir carpeta se cargan sus ajustes
- 🛡️ **Aviso de carpeta ajena** antes de analizar: aplicar los vertederos y viaductos de
  otra obra no daba error (están a 200 km y con otra cadena), pero creaba las carpetas
  de ese cliente dentro de la entrega de otro
- 🔄 **Migración automática**: en el primer arranque tu configuración actual se guarda
  como obra y queda activa, sin perder nada
- 💾 **«Guardar ajustes como obra…»** para dar de alta las demás sin editar JSON
- 📄 ADR-011

### v3.4 - Undo fiable, parseo KML sin lastre y contrato de dependencias
- 📍 **Vertederos en su propio fichero**: `landmark_kmls` permite leer `Vertederos.kml`
  **además** de la traza (antes `load_kml` reseteaba el estado y era imposible). Solo se
  fusionan los placemarks cuyo nombre no es un PK, así que apuntar por error al KML de
  traza no convierte 300 hitos en vertederos
- 📍 **Alias de carpeta para un vertedero suelto**: un grupo de un miembro ya vale, así
  que el `TP01` del KML se entrega en la carpeta `TP-01` que pide el cliente
- 🐛 **La extensión de traza ya no se extrapola**: en Torre Pacheco el eje empieza 16,7 km
  antes de la primera ancla y se inventaba un PK-1+965, reportándolo como el mayor hueco.
  El trabajo de agosto pasa de 29 % a **57 %** de cobertura y de 8 huecos a **7 reales**
- 🗺️ **Mapa base arreglado**: CARTO empezó a marcar las teselas sin clave con
  «API KEY REQUIRED». Por defecto pasa a la **ortofoto oficial PNOA del IGN**, con
  Satélite ESRI, mapa oscuro (Esri Canvas) y OSM como alternativas — todas sin API key
- 🗺️ **El mapa ya no se queda en blanco al acercar**: cada capa declara `maxNativeZoom`,
  así que Leaflet reescala en vez de pedir teselas que el servicio no sirve
- 🐛 **El buscador tapaba el control de capas**: 186 px de solape con el control
  desplegado y le robaba los clics. Ahora es un control de Leaflet y se apila con él
- 🐛 **La barra de estado dimensionaba la ventana**: con el resumen de cobertura (~300
  caracteres) el `QLabel` pedía 3576 px, así que tras cada análisis la ventana se
  agrandaba sola de 1400 a 1932 px y ya no podía encogerse (en un portátil de 1920 se
  salía de la pantalla). Ahora el texto se elide y el mensaje completo queda en el tooltip
- 🔒 **Inyección de HTML/JS desde el KML cerrada** (ADR-010): un placemark con
  `</script>` rompía el visor y uno con `<img src=x onerror=…>` ejecutaba al abrir el
  popup. Ahora el payload va escapado y la plantilla escapa antes de construir DOM;
  la lista de búsqueda se construye con `textContent`, sin `onclick` en línea
- 🐛 **Fotogramas de vídeo (SRT) fuera del renombrado**: todos compartían la ruta del
  propio `.SRT`, así que la vista previa colapsaba N filas en una y F7 intentaba renombrar
  el fichero de telemetría (4 cues → `{ok: 0, errors: 4}`). Ahora son evidencia de
  cobertura, no objetivos de renombrado (ADR-009)
- 🐛 **Undo encadenado** (crítico): un lote que libera un nombre y lo reutiliza
  (`A→B` y luego `C→A`) dejaba ficheros sin restaurar y los reportaba como «conflicto».
  El undo se reproduce ahora en orden inverso (LIFO) en los dos canales, SQLite y CSV
- ⚡ **Carga de KML 4,9× más rápida** (267 ms → 55 ms en una traza real de 500 KiB):
  la rama `fastkml` fallaba en *todas* las cargas desde fastkml 1.x y consumía el 82 %
  del tiempo antes de descartarse. `lxml` era ya el único parser que llegaba a ejecutarse
- 📦 **Una dependencia menos** (`fastkml` + `pygeoif`): fuera de requirements, del bundle
  PyInstaller y del instalador del operador
- 🛡️ **Mínimos de versión reales**: el código exige `shapely>=2.0` (`STRtree.nearest`
  devuelve índice desde 2.0; en 1.x devolvía la geometría) y `piexif>=1.1.3`
- 🧪 **Tests de contrato de dependencias**: CI y los instaladores instalan sin lockfile,
  así que las suposiciones sobre shapely/piexif/Pillow fallan con nombre y no como
  `TypeError` a mitad de análisis
- 🧪 **Dialectos KML fijados**: carpetas anidadas, `MultiGeometry`, prefijos de namespace,
  KMZ, eje sintetizado desde placemarks, documento vacío y XML malformado
- 🧪 326 tests (antes 246)
- 📄 ADR-008, ADR-009 y ADR-010

### v3.3 - Análisis sin cuellos O(n²) y QA de cobertura contra la traza
- ⚡ **Índice de sidecars por carpeta**: una sola lectura de directorio en vez de una por foto
  (2000 fotos: 6,8 s → 0,015 s; análisis completo de 800 fotos 13,4× más rápido)
- ⚡ **Partición landmark/PK cacheada**: la búsqueda del PK más cercano vuelve a ser O(log n)
  aunque haya vertederos configurados (2,3× con 400 placemarks)
- 🎯 **Cobertura relativa a la traza**: huecos de inicio y final, no solo entre fotos
- 🎯 **Umbral de hueco adaptativo** (2,5 × espaciado mediano del vuelo): en una entrega real
  pasa de 190 «huecos» ruidosos a 1 hueco verdadero de 404 m
- 📐 **% de cobertura por huella** (±50 m por foto): 65 % real en vez de un 5 % sin sentido
- 📋 **PK sin foto**: lista de placemarks del KML que no recibieron ninguna foto
  (barra de estado, banner, log, CSV y GeoJSON)
- 🐛 Sidecars revertidos ya no se registran como renombrados en el CSV de deshacer
- 🐛 Los avisos con `≥ · →` ya no rompen el log de consola en páginas de códigos no UTF-8
- 🧪 246 tests (antes 200), incluidos los primeros tests reales de `MainWindow`
- 📄 ADR-006 y ADR-007

### v3.2 - Cadena calibrada y cobertura de corredor
- 🎯 **PK oficial interpolado** entre anclas del KML (slack chainage), no solo snap al placemark más cercano
- 📏 **Umbral de corredor**: distancia perpendicular a la traza; landmarks siguen midiendo al placemark
- 🧭 **Cobertura QA**: huecos de cadena ≥ 100 m en barra de estado, CSV y GeoJSON (`Ctrl+Shift+E`)
- 📄 ADR-005 documenta la decisión frente a competidores de chainage / LRS

### v3.1 - Optimización y endurecimiento (auditoría completa)
- ⚡ **Índice espacial (STRtree)** para el PK más cercano: O(log n) en vez de escanear todos los puntos por foto
- ⚡ **Detección de duplicados por rejilla**: de O(n × kept) a ~O(n) en lotes grandes
- 🧩 **Extracción de `MainWindow`**: sesión (`session_store.py`) y recientes (`recents.py`) ahora son módulos puros sin Qt, con tests dedicados
- 🛡️ **Logging consistente en `SpatialCalculator`**: los `except: pass` silenciosos ahora registran a nivel debug/warning/info para diagnosticar KML mal formados
- 🐛 **Fix de concurrencia**: callback de fin de worker migrado de `QTimer.singleShot` (no fiable desde hilos sin *event loop*) a una señal Qt dedicada, eliminando el bloqueo "hay otra operación en curso"
- 🐛 **Fix de crash en Windows**: inicialización perezosa de `QWebEngineView` + GPU deshabilitada en Chromium embebido
- ✅ **+100 tests** (antes 83) cubriendo el índice espacial, duplicados en bordes de rejilla y los nuevos módulos puros
- 📄 Ver `docs/adr/004-spatial-index-and-session-extraction.md` para el detalle

### v3.0 - Remodelación de UI a PySide6/Qt
- 🪟 Nueva UI basada en **PySide6/Qt6** con diseño responsive y docks
- 🗺️ **Mapa embebido** con `QWebEngineView` reutilizando el generador HTML
- 🧵 **Thread-safety**: operaciones largas en `QThread`-style workers con señales
- 📜 **Pestaña de registro** alimentada por el logger real (`QtLogHandler`)
- 📊 **Barra de progreso** con cancelación efectiva y contador de elementos
- 🎨 **Temas claro/oscuro** con toggle persistente (`Ctrl+T`) en la config
- 🔙 **Deshacer renombrado** con historial SQLite + respaldo CSV
- ⌨️ Atajos equivalentes (F5–F8, Ctrl+O/K/E/T, Esc, F1) y menú completo
- 🧪 Tests nuevos para workers y `QtLogHandler`
- 🧹 Core unificado en `RenamerLogic` (sin capa `services`/`events` duplicada)

### v2.1 - Mejoras de UX y Rendimiento
- 🚀 **Caché de Procesamiento**: Evita reprocesar archivos ya analizados
- 🔍 **Detección de Duplicados**: Identifica y omite archivos duplicados automáticamente
- 🔄 **Retry Logic**: Reintentos automáticos en operaciones fallidas
- 💡 **Tooltips Informativos**: Ayuda contextual en todos los controles
- ⌨️ **Keyboard Shortcuts**: Atajos de teclado para operaciones comunes (F5-F8, Ctrl+O/E)
- 🧭 **Menú Superior**: Navegación más intuitiva con menú de aplicación
- ✅ **Validación Visual**: Indicadores visuales de rutas válidas/inválidas
- 📊 **Estadísticas de Procesamiento**: Cálculo automático de tiempos estimados
- 📝 **Sistema de Reportes**: Generación de informes detallados de procesamiento
- 🛡️ **Validación de Coordenadas**: Verificación automática de coordenadas GPS

### v2.0 - Arquitectura Moderna
- ✨ Nueva arquitectura con separación de responsabilidades
- 🔧 Sistema de eventos para comunicación desacoplada
- 📊 Logging completo con rotación de archivos
- ⚡ Mejoras de rendimiento con procesamiento paralelo
- 🎨 UI moderna con componentes reutilizables
- 🛡️ Manejo robusto de errores y validación
- 🧪 Framework de testing integrado

### v1.0 - Versión Original
- 🚀 Funcionalidad básica de renombrado
- 📍 Cálculos espaciales simples
- 🖼️ Interfaz tkinter básica

## 🤝 Contribución

### Desarrollo Local
1. Fork del repositorio
2. Crear rama de feature: `git checkout -b feature/nueva-funcionalidad`
3. Commit de cambios: `git commit -m 'Agregar nueva funcionalidad'`
4. Push a la rama: `git push origin feature/nueva-funcionalidad`
5. Crear Pull Request

### Estándares de Código
- **PEP 8**: Seguir convenciones de estilo Python
- **Type Hints**: Usar anotaciones de tipos
- **Docstrings**: Documentar funciones y clases
- **Tests**: Escribir tests para nueva funcionalidad

## ⌨️ Atajos de Teclado

### Operaciones Principales
- **F5** - Analizar imágenes
- **F6** - Vista previa
- **F7** - Procesar cambios
- **F8** - Generar mapa
- **Esc** - Cancelar operación

### Navegación
- **Ctrl+O** - Abrir carpeta
- **Ctrl+K** - Abrir archivo KML
- **Ctrl+E** - Exportar CSV
- **Ctrl+T** - Alternar tema claro/oscuro
- **F1** - Ver ayuda
- **Ctrl+Q** - Salir

## 🤖 Agentes IA (agency-agents)

Este proyecto integra [agency-agents](https://github.com/msitarzewski/agency-agents): un catálogo de especialistas IA para Cursor que ayudan a revisar código, UX, arquitectura y pruebas.

### Sincronizar reglas en Cursor

```bash
scripts\sync_agency_agents.bat
```

Esto clona o actualiza el repositorio y convierte los agentes a reglas en `.cursor/rules/`. En el chat de Cursor, invoca un agente por nombre, por ejemplo:

- `@code-reviewer` — revisión de código
- `@ui-designer` — mejoras de interfaz
- `@software-architect` — decisiones de arquitectura
- `@agents-orchestrator` — flujo completo de mejora

También puedes instalar la app de escritorio [Agency Agents](https://agencyagents.app) para gestionar agentes sin terminal.

### Flujo guiado con @agents-orchestrator

El orquestador coordina especialistas en fases. Archivos del pipeline:

| Fase | Archivo | Agente |
|------|---------|--------|
| 1 — Plan | `project-specs/renombrador-pks-setup.md` | `@senior-project-manager` |
| 2 — Tareas | `project-tasks/renombrador-pks-tasklist.md` | `@senior-project-manager` |
| 3 — Arquitectura | `docs/adr/*.md` | `@software-architect` |
| 4 — Implementar | cada tarea `[ ]` del tasklist | `@senior-developer` / `@code-reviewer` |
| 5 — QA | `scripts\run_checks.bat` | `@test-results-analyzer` |
| 6 — Cierre | revisión final | `@reality-checker` |

**Comando para lanzar el pipeline en Cursor:**

```
@agents-orchestrator Ejecuta el pipeline completo para project-specs/renombrador-pks-setup.md:
senior-project-manager → software-architect → [senior-developer ↔ test-results-analyzer por tarea]
→ reality-checker. Marca cada tarea en project-tasks/renombrador-pks-tasklist.md al pasar QA.
```

**Por tarea individual:**

```
@agents-orchestrator Implementa la tarea T5 del tasklist con @senior-developer
y valida con pytest antes de marcar [x].
```

## 📄 Licencia

Este proyecto está licenciado bajo los términos de la Licencia MIT.

## 📞 Soporte

Para reportar problemas o solicitar ayuda:
1. Revisa la sección de solución de problemas
2. Consulta los logs en `logs/` para errores detallados
3. Crea un issue en el repositorio con:
   - Descripción detallada del problema
   - Pasos para reproducir
   - Logs relevantes
   - Capturas de pantalla si aplica

---

**Desarrollado con ❤️ para el equipo de AEROSCAN**
