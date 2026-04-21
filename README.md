# 📍 Renombrador PKS - Sistema Avanzado

Aplicación de escritorio para renombrar fotografías aéreas basándose en su proximidad a puntos kilométricos (PK) definidos en archivos KML/KMZ.

## 🚀 Características Principales

### ✨ Funcionalidades Avanzadas
- **Procesamiento por Lotes**: Analiza y renombra cientos de imágenes simultáneamente
- **Cálculo Espacial Preciso**: Determina la distancia exacta de cada foto a la traza PK
- **Soporte Múltiple Formatos**: JPG, PNG, TIFF, BMP, KML, KMZ, GeoJSON, SRT
- **Vista Previa Interactiva**: Revisa los cambios antes de aplicarlos
- **Mapas Interactivos**: Visualización geográfica de los resultados
- **Exportación CSV**: Análisis de datos en hojas de cálculo

### 🛠️ Mejoras Técnicas
- **Arquitectura Moderna**: Separación clara de responsabilidades
- **Sistema de Eventos**: Comunicación desacoplada entre componentes
- **Logging Completo**: Registro detallado de operaciones y errores
- **Configuración Validada**: Gestión robusta de parámetros
- **Procesamiento Paralelo**: Optimización de rendimiento con hilos
- **Manejo de Errores**: Recuperación elegante de fallos

## 📋 Requisitos del Sistema

- **Python 3.8+**
- **Windows 10/11** (recomendado)
- **4GB+ RAM**
- **Espacio en disco** para imágenes y copias de seguridad

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

## 📦 Dependencias

- **ttkbootstrap**: Interfaz moderna con temas
- **shapely**: Operaciones geométricas
- **fastkml**: Procesamiento KML/KMZ
- **Pillow**: Manipulación de imágenes
- **piexif**: Lectura de datos EXIF
- **lxml**: Procesamiento XML
- **tkintermapview**: Componentes de mapa
- **pysrt**: Procesamiento de subtítulos

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
├── core/                    # Lógica de negocio
│   ├── config.py           # Gestión de configuración
│   ├── events.py           # Sistema de eventos
│   ├── logging_config.py   # Configuración de logging
│   ├── services.py         # Servicios de negocio
│   ├── models.py           # Modelos de datos
│   ├── renamer_logic.py    # Lógica de renombrado
│   ├── spatial_calculator.py # Cálculos espaciales
│   └── video_extractor.py  # Extracción de video
├── ui/                      # Interfaz de usuario
│   ├── components/         # Componentes reutilizables
│   │   ├── base.py         # Componentes base
│   │   ├── sidebar.py      # Barra lateral
│   │   └── tabs.py         # Panel de pestañas
│   └── main_window_new.py  # Ventana principal
└── map_component.py         # Gestor de mapas
```

### Patrones de Diseño
- **MVC**: Separación Modelo-Vista-Controlador
- **Event-Driven**: Comunicación asíncrona entre componentes
- **Service Layer**: Lógica de negocio encapsulada
- **Dependency Injection**: Inyección de dependencias

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
- **F1** - Ver ayuda
- **Alt+F4** - Salir

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
