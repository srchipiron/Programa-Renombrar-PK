"""A single report the operator can send when something goes wrong.

Debugging this app remotely means asking a chain of questions: which build,
run from source or installed, where does it keep its settings, which corridor
was loaded, was the trace reachable, what did the log say. During development
a launch failed once and could not be reproduced because none of that was
recorded anywhere the operator could hand over.

This assembles all of it into one text file. Deliberately Qt-free so it can be
unit-tested: the UI injects what only it knows (Qt versions, the analysis in
memory) and everything else is read here.

**The report contains real paths**, which on these jobs carry client names.
That is the point — it is meant to be sent to whoever is helping — but the
header says so, so nobody pastes it somewhere public by accident.
"""
from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import paths
from .version import ORGANISATION, version_line

#: Tail of each log file included in the report.
LOG_TAIL_LINES = 40
#: Third-party packages whose versions have already caused surprises here.
_TRACKED_PACKAGES = ("PySide6", "shapely", "Pillow", "piexif", "lxml", "pysrt")


def _package_versions() -> Dict[str, str]:
    import importlib.metadata as metadata

    out: Dict[str, str] = {}
    for name in _TRACKED_PACKAGES:
        try:
            out[name] = metadata.version(name)
        except Exception:
            out[name] = "no instalado"
    return out


def _tail(path: Path, lines: int = LOG_TAIL_LINES) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()[-lines:]
    except OSError:
        return []


def _newest_log(prefix: str) -> Optional[Path]:
    try:
        candidates = sorted(paths.logs_dir().glob(f"{prefix}_*.log"))
    except OSError:
        return None
    return candidates[-1] if candidates else None


def _path_state(value: str) -> str:
    """Render a path together with whether it is actually reachable.

    Half the incidents on these jobs are a network share that was not mounted,
    so "the KML is configured" and "the KML can be read" must not look alike.
    """
    if not value:
        return "(sin definir)"
    try:
        if os.path.isdir(value):
            return f"{value}  [carpeta OK]"
        if os.path.isfile(value):
            return f"{value}  [OK]"
    except OSError:
        return f"{value}  [ERROR AL COMPROBAR]"
    return f"{value}  [NO ACCESIBLE]"


def _section(title: str) -> str:
    return f"\n## {title}\n"


def collect_diagnostics(
    *,
    config: Any = None,
    project: Any = None,
    analysis: Optional[Dict[str, Any]] = None,
    coverage: Any = None,
    spatial: Any = None,
    qt: Optional[Dict[str, str]] = None,
    extra: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """Build the report. Every argument is optional: a diagnostic must be
    obtainable even when the app is in a broken state."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    lines: List[str] = [
        f"# Diagnóstico · {version_line()}",
        "",
        f"Generado: {stamp}",
        "",
        "> Contiene rutas reales de trabajo (nombres de cliente incluidos).",
        "> Envíalo solo a quien te esté ayudando.",
    ]

    # -- Ejecución -----------------------------------------------------
    lines.append(_section("Ejecución"))
    lines.append(f"- Empaquetado: {'ejecutable (PyInstaller)' if paths.is_frozen() else 'código fuente'}")
    lines.append(f"- Python: {sys.version.split()[0]} ({sys.executable})")
    lines.append(f"- Sistema: {platform.platform()}")
    lines.append(f"- Organización: {ORGANISATION}")
    for clave, valor in (qt or {}).items():
        lines.append(f"- {clave}: {valor}")
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    if flags:
        lines.append(f"- Flags de Chromium: {flags}")

    # -- Rutas ---------------------------------------------------------
    lines.append(_section("Rutas"))
    data = paths.data_dir()
    modo = "junto al ejecutable (portable)" if data == paths.app_dir() else "en %LOCALAPPDATA%"
    lines.append(f"- Carpeta de la aplicación: {paths.app_dir()}")
    lines.append(f"- Carpeta de datos: {data}  [{modo}]")
    lines.append(f"- Recursos: {paths.resource_dir()}")
    lines.append(f"- Registros: {_path_state(str(paths.logs_dir()))}")

    # -- Dependencias --------------------------------------------------
    lines.append(_section("Dependencias"))
    for nombre, version in _package_versions().items():
        lines.append(f"- {nombre}: {version}")

    # -- Obra activa ---------------------------------------------------
    lines.append(_section("Obra activa"))
    if project is None:
        lines.append("- (ninguna seleccionada)")
    else:
        lines.append(f"- Nombre: {getattr(project, 'name', '?')}")
        lines.append(f"- Ámbito: {_path_state(getattr(project, 'root', ''))}")
        lines.append(f"- Traza: {_path_state(getattr(project, 'kml', ''))}")
        if spatial is not None:
            # Whether the trace actually loaded, not just whether the file is
            # readable: a KML with no LineString answers 0 to every PK.
            try:
                lines.append(f"- Estado de la traza: {spatial.axis_summary()}")
            except Exception as exc:  # pragma: no cover - defensivo
                lines.append(f"- Estado de la traza: no se pudo determinar ({exc})")
        for kml in getattr(project, "landmark_kmls", []) or []:
            lines.append(f"- Vertederos: {_path_state(kml)}")
        lines.append(f"- Umbral: {getattr(project, 'threshold', '?')} m · Sufijo: {getattr(project, 'suffix', '')!r}")
        lines.append(
            f"- Viaductos: {len(getattr(project, 'viaduct_pks', []) or [])} PK · "
            f"Vertederos en config: {len(getattr(project, 'extra_landmarks', []) or [])}"
        )

    # -- Configuración -------------------------------------------------
    if config is not None:
        lines.append(_section("Configuración"))
        for campo in (
            "active_project", "threshold", "landmark_threshold", "landmark_capture_radius",
            "max_workers", "iqr_multiplier", "create_backup", "auto_refresh_preview",
            "theme", "log_level",
        ):
            if hasattr(config, campo):
                lines.append(f"- {campo}: {getattr(config, campo)}")
        lines.append(f"- Carpeta de trabajo: {_path_state(getattr(config, 'last_folder', ''))}")

    # -- Estado del análisis -------------------------------------------
    lines.append(_section("Último análisis"))
    if not analysis:
        lines.append("- (sin análisis en esta sesión)")
    else:
        for clave, valor in analysis.items():
            lines.append(f"- {clave}: {valor}")

    if coverage is not None and getattr(coverage, "inside_count", 0):
        lines.append(_section("Cobertura"))
        lines.append(f"- {coverage.status_line(max_gaps=3)}")
        faltan = getattr(coverage, "missing_pks", []) or []
        if faltan:
            muestra = ", ".join(m.label for m in faltan[:15])
            resto = len(faltan) - 15
            lines.append(
                f"- PK sin foto ({len(faltan)}/{getattr(coverage, 'pk_total', 0)}): "
                f"{muestra}{f' (+{resto} más)' if resto > 0 else ''}"
            )

    # -- Registros -----------------------------------------------------
    for etiqueta, prefijo in (("Errores recientes", "errors"), ("Registro reciente", "app")):
        lines.append(_section(etiqueta))
        archivo = _newest_log(prefijo)
        if archivo is None:
            lines.append("- (sin registros)")
            continue
        cola = _tail(archivo)
        if not cola:
            lines.append(f"- {archivo.name}: vacío")
            continue
        lines.append(f"```\n{archivo.name}")
        lines.extend(cola)
        lines.append("```")

    for clave, valor in (extra or {}).items():
        lines.append(f"\n- {clave}: {valor}")

    return "\n".join(lines) + "\n"


def default_filename(now: Optional[datetime] = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return f"diagnostico_pks_{stamp}.txt"


def write_diagnostics(destination: str | Path, report: str) -> Path:
    """Write the report, creating the folder if needed."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return path


def summarise_items(items: Sequence[Any]) -> Dict[str, Any]:
    """Counts the UI would otherwise have to recompute for the report."""
    total = len(items)
    dentro = sum(1 for i in items if getattr(i, "is_inside_threshold", False) and not getattr(i, "excluded", False))
    excluidas = sum(1 for i in items if getattr(i, "excluded", False))
    virtuales = sum(1 for i in items if getattr(i, "virtual", False))
    duplicadas = sum(1 for i in items if getattr(i, "duplicate_of", None))
    con_sidecar = sum(1 for i in items if getattr(i, "sidecars", None))
    return {
        "fotos analizadas": total,
        "dentro del umbral": dentro,
        "fuera": total - dentro - excluidas,
        "excluidas": excluidas,
        "fotogramas de vídeo": virtuales,
        "duplicadas detectadas": duplicadas,
        "con ficheros acompañantes": con_sidecar,
    }
