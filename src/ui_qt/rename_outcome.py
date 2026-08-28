"""Pure helpers that classify rename-batch outcomes for operator messaging."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RenameOutcome:
    """Operator-facing interpretation of ``process_images`` stats."""

    ok: int
    skipped: int
    errors: int
    cancelled: int
    status_line: str
    is_partial: bool
    is_empty: bool
    offer_undo: bool
    dialog_title: str
    dialog_body: str


def is_unc_path(path: str | None) -> bool:
    """Return True for Windows UNC / SMB paths (``\\\\server\\share``)."""
    text = (path or "").strip().replace("/", "\\")
    return text.startswith("\\\\")


def backup_risk_note(*, folder: str, create_backup: bool) -> str:
    """Extra confirm-dialog text when renaming without backup on a network share."""
    if create_backup or not is_unc_path(folder):
        return ""
    return (
        "\n\n⚠ Carpeta de red (UNC) sin copia de seguridad.\n"
        "Si falla a mitad de lote, no habrá `_backup_originales` "
        "para recuperar. Se recomienda activar «Crear copia de seguridad»."
    )


def classify_rename_outcome(stats: Mapping[str, Any] | None) -> RenameOutcome:
    """Turn raw rename stats into a recoverable operator message.

    Partial batches (cancel mid-run or mixed errors) keep disk changes that
    are already undoable via SQLite/CSV when ``ok > 0``. Stuck renames
    (``ok == 0`` but a non-empty ``mapping`` after failed rollback) are also
    treated as recoverable so the operator is offered Undo.
    """
    raw = stats if isinstance(stats, Mapping) else {}
    ok_n = int(raw.get("ok", 0) or 0)
    skipped = int(raw.get("skipped", 0) or 0)
    errors = int(raw.get("errors", 0) or 0)
    cancelled = int(raw.get("cancelled", 0) or 0)
    mapping = raw.get("mapping") if isinstance(raw.get("mapping"), Mapping) else {}
    stuck_count = len(mapping) if ok_n == 0 and mapping else 0

    status_line = (
        f"Renombrado completado: {ok_n} OK, "
        f"{skipped} omitidos, {errors} errores."
    )
    if cancelled:
        status_line += f" {cancelled} cancelados."
    if stuck_count:
        status_line += f" {stuck_count} retenidos en disco."

    is_empty = ok_n == 0 and stuck_count == 0
    is_partial = (ok_n > 0 and (cancelled > 0 or errors > 0)) or stuck_count > 0
    offer_undo = (ok_n > 0 and (cancelled > 0 or errors > 0)) or stuck_count > 0

    if is_empty:
        title = "Renombrado sin cambios"
        body = (
            "No se renombró ningún archivo.\n\n"
            "Comprueba que:\n"
            "• Pulsaste «Sí» en la confirmación\n"
            "• Hay fotos «Dentro» del umbral en la vista previa (F6)\n"
            "• No cancelaste con Esc durante el proceso"
        )
        if errors:
            body += f"\n• Revisa el registro: {errors} error(es) de disco"
        if cancelled:
            body += f"\n• Se cancelaron {cancelled} operaciones"
    elif stuck_count > 0 and ok_n == 0:
        title = "Renombrado incompleto"
        body = (
            f"Ningún archivo se contabilizó como OK, pero {stuck_count} "
            "quedaron con el nombre nuevo en disco tras un error "
            "(p. ej. fallo de metadatos sin poder revertir).\n\n"
            "Usa Deshacer para restaurar los nombres originales."
        )
    elif is_partial:
        title = "Renombrado parcial"
        reason = []
        if cancelled:
            reason.append(
                f"Se canceló el proceso tras renombrar {ok_n} archivo(s)."
            )
        if errors:
            reason.append(f"Hubo {errors} error(es) de disco o metadatos.")
        body = (
            "\n".join(reason)
            + f"\n\nOK: {ok_n} · Omitidos: {skipped} · "
            f"Errores: {errors} · Cancelados: {cancelled}\n\n"
            "Los archivos ya renombrados quedan registrados para Deshacer.\n"
            "Puedes revertirlos ahora o abrir la carpeta para revisarlos."
        )
    else:
        title = "Renombrado completado"
        body = status_line

    return RenameOutcome(
        ok=ok_n,
        skipped=skipped,
        errors=errors,
        cancelled=cancelled,
        status_line=status_line,
        is_partial=is_partial,
        is_empty=is_empty,
        offer_undo=offer_undo,
        dialog_title=title,
        dialog_body=body,
    )
