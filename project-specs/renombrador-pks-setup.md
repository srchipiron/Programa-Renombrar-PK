# Renombrador PKS — Especificación de mejora (orquestador)

## Objetivo

Endurecer seguridad de datos, concurrencia y calidad de pruebas del renombrador de fotos aéreas por proximidad PK, sin cambiar el alcance funcional acordado (app de escritorio PySide6, monolito modular).

## Requisitos exactos

1. **KML obligatorio** antes de analizar (la app depende de la traza espacial).
2. **Workers aislados** en análisis: no mutar `SpatialCalculator` / `RenamerLogic` compartidos desde hilos de fondo.
3. **Renombrado secuencial** en disco para reducir estados parciales al cancelar (ADR-003 documenta ausencia de rollback).
4. **Copia de seguridad activa por defecto** y umbral inicial coherente con auto-umbral (30 m).
5. **Restauración de sesión** debe recargar carpeta, KML y estado espacial.
6. **Diálogo de renombrado** debe bloquear o advertir explícitamente ante conflictos.
7. **Tests de integración** para `process_images` (renombrado real en carpeta temporal).
8. **Accesibilidad mínima** en vista previa: columna de inclusión etiquetada y estado no solo por color.

## Restricciones

- Mantener `src/core/` libre de PySide6.
- No introducir servicios externos ni APIs de red.
- Cada tarea debe pasar `python -m pytest tests/ -q` antes de avanzar.

## Referencias

- `docs/adr/001-modular-monolith.md`
- `docs/adr/002-undo-dual-channel.md`
- `docs/adr/003-qt-worker-boundary.md`

## Criterio de éxito

- 81+ tests pasando.
- Flujo operador: carpeta + KML → F5 → F6 → F7 sin regresiones.
- Pipeline del orquestador documentado en `project-tasks/renombrador-pks-tasklist.md`.
