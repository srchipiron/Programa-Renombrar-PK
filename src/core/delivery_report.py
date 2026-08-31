"""The document that goes out with the delivery.

The program already computed everything a monthly hand-over needs — coverage,
chainage span, holes, PK posts with no photo, the routing of every file — but
it scattered it across three separate exports the operator recomposed by hand
each month. This assembles it into one self-contained HTML: no external assets,
printable to PDF from the browser, no new dependency.

Qt-free so it can be unit-tested, and every value that reaches the page is
escaped: photo names come from the filesystem and PK labels from the client's
KML (ADR-010).
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .coverage import GAP_HEAD, GAP_INTERIOR, GAP_TAIL, CoverageReport
from .models import PhotoItem
from .naming import month_tokens_from_path
from .spatial_calculator import SpatialCalculator
from .version import ORGANISATION, version_line

logger = logging.getLogger(__name__)

_TEMPLATE_NAME = "report_template.html"

_GAP_NAMES = {
    GAP_HEAD: "Inicio de traza",
    GAP_INTERIOR: "Interior",
    GAP_TAIL: "Final de traza",
}


def _template_path() -> Path:
    from .paths import resource_dir

    return resource_dir() / "src" / "assets" / _TEMPLATE_NAME


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _pk(metres: Optional[float]) -> str:
    if metres is None:
        return "—"
    return f"PK-{SpatialCalculator.format_pk_label(metres)}"


def _period_label(folder: str) -> str:
    """"Agosto 2026" from the delivery folder, or the folder's own name."""
    tokens = month_tokens_from_path(folder)
    if tokens:
        return f"{tokens['MES_LARGO']} {tokens['AAAA']}"
    return os.path.basename(os.path.normpath(folder)) if folder else "—"


def _field(label: str, value: Any) -> str:
    return f"<div><b>{_esc(label)}</b>{_esc(value)}</div>"


def _kpi(number: Any, label: str, tone: str = "") -> str:
    clase = f"kpi {tone}".strip()
    return f'<div class="{clase}"><div class="n">{_esc(number)}</div><div class="t">{_esc(label)}</div></div>'


def _coverage_bar(coverage: CoverageReport) -> str:
    """Inline SVG of the trace with its holes, drawn to scale.

    A percentage says how much is covered; this says *where* the holes are,
    which is what decides whether anyone has to fly again.
    """
    lo = coverage.trace_start_pk_m
    hi = coverage.trace_end_pk_m
    if lo is None or hi is None or hi <= lo:
        return '<div class="nota">Sin traza de referencia: no se puede situar la cobertura.</div>'

    span = hi - lo
    ancho, alto = 1000.0, 34.0
    partes = [
        f'<svg viewBox="0 0 {ancho:.0f} {alto + 22:.0f}" width="100%" height="56" '
        'role="img" aria-label="Cobertura de la traza">',
        f'<rect x="0" y="0" width="{ancho:.0f}" height="{alto:.0f}" fill="#16a34a" rx="4"/>',
    ]
    for hueco in coverage.gaps:
        inicio = max(lo, hueco.start_pk_m)
        fin = min(hi, hueco.end_pk_m)
        if fin <= inicio:
            continue
        x = (inicio - lo) / span * ancho
        w = max(1.0, (fin - inicio) / span * ancho)
        partes.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{alto:.0f}" fill="#dc2626"/>'
        )
    partes.append(
        f'<text x="0" y="{alto + 16:.0f}" font-size="13" fill="#64748b">{_esc(_pk(lo))}</text>'
    )
    partes.append(
        f'<text x="{ancho:.0f}" y="{alto + 16:.0f}" font-size="13" fill="#64748b" '
        f'text-anchor="end">{_esc(_pk(hi))}</text>'
    )
    partes.append("</svg>")
    return "".join(partes)


def _gaps_table(coverage: CoverageReport) -> str:
    if not coverage.gaps:
        return '<p class="vacio">Sin huecos: la traza queda cubierta de extremo a extremo.</p>'
    filas = [
        "<tr>"
        f"<td>{_esc(_pk(g.start_pk_m))}</td>"
        f"<td>{_esc(_pk(g.end_pk_m))}</td>"
        f'<td class="num">{g.length_m:,.0f}</td>'
        f"<td>{_esc(_GAP_NAMES.get(g.kind, g.kind))}</td>"
        "</tr>"
        for g in sorted(coverage.gaps, key=lambda g: -g.length_m)
    ]
    return (
        "<table><thead><tr><th>Desde</th><th>Hasta</th>"
        "<th style='text-align:right'>Longitud (m)</th><th>Tipo</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table>"
    )


def _missing_pk_list(coverage: CoverageReport) -> str:
    faltan = coverage.missing_pks
    if not faltan:
        if not coverage.pk_total:
            return '<p class="nota">La traza no define puntos kilométricos con nombre.</p>'
        return '<p class="vacio">Todos los puntos kilométricos tienen fotografía.</p>'
    etiquetas = "".join(f"<span>{_esc(m.label)}</span>" for m in faltan)
    return (
        f'<p class="nota">{len(faltan)} de {coverage.pk_total} sin fotografía '
        f"a menos de {coverage.pk_tolerance_m:.0f} m.</p>"
        f'<div class="pks">{etiquetas}</div>'
    )


def _destinations_table(items: Sequence[PhotoItem]) -> str:
    reparto: Dict[str, int] = {}
    for item in items:
        if not item.new_name_base or item.excluded or not item.is_inside_threshold:
            continue
        reparto[item.dest_rel or "(raíz)"] = reparto.get(item.dest_rel or "(raíz)", 0) + 1
    if not reparto:
        return '<p class="nota">Ninguna fotografía entra en el renombrado.</p>'
    filas = "".join(
        f"<tr><td>{_esc(carpeta)}</td><td class='num'>{cuenta}</td></tr>"
        for carpeta, cuenta in sorted(reparto.items(), key=lambda kv: (-kv[1], kv[0]))
    )
    return (
        "<table><thead><tr><th>Carpeta</th>"
        "<th style='text-align:right'>Fotografías</th></tr></thead>"
        f"<tbody>{filas}</tbody></table>"
    )


def _index_table(items: Sequence[PhotoItem], plan: Optional[Dict[str, str]]) -> str:
    entregables = [
        it for it in items
        if it.new_name_base and not it.excluded and it.is_inside_threshold
    ]
    if not entregables:
        return '<p class="nota">Ninguna fotografía entra en el renombrado.</p>'
    filas = []
    for item in sorted(entregables, key=lambda i: (float(i.pk_value or 0.0), i.name)):
        nombre = (plan or {}).get(item.path) or item.new_name_base
        fecha = f"{item.date_str[:4]}-{item.date_str[4:6]}-{item.date_str[6:8]}" if len(item.date_str) == 8 else "—"
        distancia = "—" if item.distance == float("inf") else f"{item.distance:.1f}"
        filas.append(
            "<tr>"
            f"<td>{_esc(item.pk_display or _pk(item.pk_value))}</td>"
            f"<td>{_esc(nombre)}</td>"
            f"<td>{_esc(item.dest_rel or '(raíz)')}</td>"
            f"<td>{_esc(item.view_label or '—')}</td>"
            f"<td>{_esc(fecha)}</td>"
            f'<td class="num">{distancia}</td>'
            f"<td>{_esc(item.name)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>PK</th><th>Archivo entregado</th><th>Carpeta</th>"
        "<th>Vista</th><th>Fecha</th><th style='text-align:right'>Dist. (m)</th>"
        "<th>Original</th></tr></thead>"
        f"<tbody>{''.join(filas)}</tbody></table>"
    )


def build_delivery_report(
    items: Sequence[PhotoItem],
    coverage: CoverageReport,
    *,
    project_name: str = "",
    folder: str = "",
    kml: str = "",
    threshold: float = 0.0,
    threshold_method: str = "",
    plan: Optional[Dict[str, str]] = None,
    now: Optional[datetime] = None,
) -> str:
    """Render the delivery report as a self-contained HTML document."""
    stamp = (now or datetime.now()).strftime("%d/%m/%Y %H:%M")

    total = len(items)
    dentro = sum(1 for i in items if i.is_inside_threshold and not i.excluded)
    excluidas = sum(1 for i in items if i.excluded)
    fuera = total - dentro - excluidas
    entregables = sum(
        1 for i in items if i.new_name_base and not i.excluded and i.is_inside_threshold
    )

    ratio = coverage.coverage_ratio
    cobertura_txt = "—" if ratio is None else f"{ratio * 100:.0f}%"
    tono_cobertura = "" if ratio is None else ("ok" if ratio >= 0.9 else "aviso" if ratio >= 0.6 else "mal")
    faltan = len(coverage.missing_pks)

    kpis = [
        _kpi(total, "Fotografías analizadas"),
        _kpi(entregables, "En la entrega", "ok"),
        _kpi(fuera, "Fuera del umbral", "aviso" if fuera else ""),
        _kpi(cobertura_txt, "Traza cubierta", tono_cobertura),
        _kpi(
            f"{coverage.covered_pk_count}/{coverage.pk_total}" if coverage.pk_total else "—",
            "PK con fotografía",
            "mal" if faltan else "ok",
        ),
        _kpi(len(coverage.gaps), "Huecos detectados", "aviso" if coverage.gaps else "ok"),
    ]
    if excluidas:
        kpis.append(_kpi(excluidas, "Excluidas a mano"))

    ficha = [
        _field("Periodo", _period_label(folder)),
        _field("Carpeta", folder or "—"),
        _field("Traza", os.path.basename(kml) if kml else "—"),
        _field("Umbral aplicado", f"{threshold:.1f} m" + (f" · {threshold_method}" if threshold_method else "")),
        _field("Extensión de traza", f"{_pk(coverage.trace_start_pk_m)} – {_pk(coverage.trace_end_pk_m)}"),
        _field("Fotografías con PK", f"{_pk(coverage.pk_min_m)} – {_pk(coverage.pk_max_m)}"),
    ]

    nota_cobertura = (
        f"Verde: traza a menos de {coverage.pk_tolerance_m:.0f} m de una fotografía. "
        f"Rojo: huecos de {coverage.gap_min_m:.0f} m o más"
        + (" (umbral deducido de la cadencia del vuelo)." if coverage.gap_min_auto else ".")
    )

    # Two kinds of substitution, kept apart on purpose: text goes through the
    # escaper, markup is already built from escaped pieces. Mixing them is how
    # an unescaped photo name would end up in the page.
    texto = {
        "__TITULO__": f"Informe de entrega · {project_name or 'Renombrador PKS'}",
        "__ORGANIZACION__": ORGANISATION,
        "__OBRA__": project_name or "Entrega fotográfica",
        "__PERIODO__": f"{_period_label(folder)} · generado el {stamp}",
        "__NOTA_COBERTURA__": nota_cobertura,
        "__PIE_IZQUIERDA__": version_line(),
        "__PIE_DERECHA__": f"Generado el {stamp}",
    }
    marcado = {
        "__FICHA__": "".join(ficha),
        "__KPIS__": "".join(kpis),
        "__BARRA_COBERTURA__": _coverage_bar(coverage),
        "__TABLA_HUECOS__": _gaps_table(coverage),
        "__LISTA_PKS__": _missing_pk_list(coverage),
        "__TABLA_DESTINOS__": _destinations_table(items),
        "__TABLA_INDICE__": _index_table(items, plan),
    }

    documento = _template_path().read_text(encoding="utf-8")
    for marca, valor in texto.items():
        documento = documento.replace(marca, _esc(valor))
    for marca, valor in marcado.items():
        documento = documento.replace(marca, valor)
    return documento


def default_filename(folder: str = "", now: Optional[datetime] = None) -> str:
    tokens = month_tokens_from_path(folder)
    if tokens:
        return f"informe_entrega_{tokens['MES']}{tokens['AA']}.html"
    stamp = (now or datetime.now()).strftime("%Y%m%d")
    return f"informe_entrega_{stamp}.html"


def write_delivery_report(destination: str | Path, document: str) -> Path:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")
    logger.info("Informe de entrega escrito en %s", path)
    return path
