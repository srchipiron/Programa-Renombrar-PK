"""Month and year tokens taken from the delivery folder.

The filename suffix carries the month of the delivery (``[PK]-AGO26``), and it
was typed by hand every month. That is a value which is stale by construction:
a corridor's settings are reused month after month, so whatever is stored is
last month's. The Pulpí-Vera tree shows the shape of the failure — the folder
``2026/5.Mayo`` holds files named ``…-ABR26``.

The delivery tree already states the month: ``…/CLIENTES/<obra>/<año>/<mes>/``.
Writing ``[PK]-{MES}{AA}`` in the suffix resolves it from there, so the stored
template stops going stale. Literal suffixes keep working untouched — this only
does anything when a token is present.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional

#: Folders are named ``8.Agosto``, ``5.Mayo``, ``7.JULIO`` — number, then month.
_MONTHS = {
    "enero": ("ENE", 1),
    "febrero": ("FEB", 2),
    "marzo": ("MAR", 3),
    "abril": ("ABR", 4),
    "mayo": ("MAY", 5),
    "junio": ("JUN", 6),
    "julio": ("JUL", 7),
    "agosto": ("AGO", 8),
    "septiembre": ("SEP", 9),
    "setiembre": ("SEP", 9),
    "octubre": ("OCT", 10),
    "noviembre": ("NOV", 11),
    "diciembre": ("DIC", 12),
}

_YEAR_RE = re.compile(r"^(20\d{2})$")
_MONTH_FOLDER_RE = re.compile(r"^\d{1,2}[.\-_ ]*(?P<nombre>[A-Za-zÁÉÍÓÚáéíóúñÑ]+)$")

#: Tokens accepted in the suffix, case-insensitive.
TOKENS = ("{MES}", "{MES_LARGO}", "{AA}", "{AAAA}")


def _month_from_folder(name: str) -> Optional[tuple]:
    match = _MONTH_FOLDER_RE.match(name.strip())
    candidate = match.group("nombre") if match else name.strip()
    entry = _MONTHS.get(candidate.casefold())
    if entry is None:
        return None
    return entry[0], candidate.capitalize(), entry[1]


def month_tokens_from_path(folder: str) -> Optional[Dict[str, str]]:
    """Return ``{MES, MES_LARGO, AA, AAAA}`` for a delivery folder, or ``None``.

    Walks the path outwards, so it works whether the operator picked the month
    folder itself or something below it (``2026/5.Mayo/1.Editadas``). The year
    is the nearest ancestor that looks like one; without it the month alone is
    not enough to build a suffix.
    """
    if not folder:
        return None
    try:
        parts = list(Path(os.path.normpath(str(folder))).parts)
    except (OSError, ValueError):
        return None

    for index in range(len(parts) - 1, -1, -1):
        month = _month_from_folder(parts[index])
        if month is None:
            continue
        short, long_name, _number = month
        for year_index in range(index - 1, -1, -1):
            year_match = _YEAR_RE.match(parts[year_index].strip())
            if year_match:
                year = year_match.group(1)
                return {
                    "MES": short,
                    "MES_LARGO": long_name,
                    "AA": year[2:],
                    "AAAA": year,
                }
        return None
    return None


def has_tokens(suffix: str) -> bool:
    upper = (suffix or "").upper()
    return any(token in upper for token in TOKENS)


def resolve_suffix(suffix: str, folder: str) -> str:
    """Replace month/year tokens in ``suffix`` using ``folder``.

    Returns the suffix untouched when it carries no tokens, or when the folder
    does not name a month — better a visible ``{MES}`` in the preview than a
    silently wrong month in a delivery.
    """
    if not has_tokens(suffix):
        return suffix
    tokens = month_tokens_from_path(folder)
    if tokens is None:
        return suffix
    out = suffix
    for name, value in tokens.items():
        out = re.sub(r"\{" + name + r"\}", value, out, flags=re.IGNORECASE)
    return out
