# Flujo operativo — Renombrador PKS

## Ciclo estándar (5 minutos de preparación + tiempo de análisis)

| Paso | Acción | Atajo | Automatización |
|------|--------|-------|----------------|
| 1 | Carpeta de brutos + KML/KMZ | Arrastrar a la ventana o Examinar | Recientes en menú Archivo; Analizar se habilita solo con ambos válidos |
| 2 | Analizar EXIF y distancias | F5 | Umbral = distancia a traza; PK calibrado; caché `.pk_exif_cache.json` |
| 3 | Ajustar umbral / sufijo (opcional) | Spinners · Auto-umbral | Worker en segundo plano (Esc cancela); vista previa auto (400 ms) si `auto_refresh_preview` |
| 4 | Revisar tabla, cobertura y exclusiones | Filtros en pestaña | Barra de estado y banner: % de traza cubierta, huecos (umbral automático según la cadencia del vuelo) y PK sin foto |
| 5 | Renombrar | F7 | Recalcula nombres (PK interpolado) antes de confirmar |
| 6 | (Opcional) Mapa / CSV / GeoJSON | F8 / Ctrl+E / Ctrl+Shift+E | GeoJSON con fotos, huecos (inicio/interior/final) y PK sin foto; CSV con resumen de cobertura |
| 7 | (Si error) Deshacer | Botón o menú | SQLite → CSV fallback; Ctrl+H historial |

## Renombrado parcial (Esc a mitad de F7)

No hay transacción «todo o nada»: los archivos ya renombrados quedan en disco y
registrados para Deshacer (SQLite + CSV). El diálogo de fin ofrece:

1. **Deshacer ahora** — revierte el lote registrado
2. **Abrir carpeta** — inspección manual
3. **Cerrar** — dejar el estado parcial y seguir

## Desarrollo

```bat
scripts\run_checks.bat
```

CI equivalente: `.github/workflows/ci.yml` (Windows + pytest offscreen).

## Build distribución

```bat
build.bat
```

Opcional: `iscc installer.iss` con Inno Setup 6.
