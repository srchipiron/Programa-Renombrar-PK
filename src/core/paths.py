"""Where the application reads its resources and writes its state.

Running from source, everything lives next to ``main.py`` and that is what the
project has always assumed. Once the app is frozen and installed, that
assumption breaks in two different ways:

* ``Path(__file__).parents[2]`` points inside the bundle, not at the app;
* the install folder may be read-only (``C:\\Program Files``), so writing
  ``config.json``, ``logs/`` or ``proyectos/`` there fails.

Both modes matter here: the app is handed over as a portable folder *and* as an
installer. So state goes next to the executable when that folder is writable —
a copied folder or a USB stick stays self-contained — and falls back to
``%LOCALAPPDATA%`` when it is not.
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Folder created under ``%LOCALAPPDATA%`` when the app folder is read-only.
APP_NAME = "RenombradorPKS"

_data_dir_cache: Optional[Path] = None


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder the application lives in.

    The executable's folder when frozen, the project root when running from
    source (``src/core/paths.py`` → two levels up).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """Folder holding read-only files shipped with the app.

    PyInstaller unpacks bundled data under ``sys._MEIPASS`` (``_internal`` in a
    onedir build); from source it is the project root.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return app_dir()


def _is_writable(directory: Path) -> bool:
    """Probe by actually creating a file: permissions alone lie on Windows."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".w_", delete=True):
            return True
    except (OSError, PermissionError):
        return False


def data_dir() -> Path:
    """Folder for state the app writes: config, logs, projects, undo history.

    Portable first, so handing someone the folder hands them their settings
    too. Falls back to ``%LOCALAPPDATA%/RenombradorPKS`` when the app folder
    cannot be written to, which is what an installed copy hits.
    """
    global _data_dir_cache
    if _data_dir_cache is not None:
        return _data_dir_cache

    candidate = app_dir()
    if _is_writable(candidate):
        _data_dir_cache = candidate
    else:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        fallback = Path(base) / APP_NAME if base else Path.home() / f".{APP_NAME.lower()}"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Nowhere left to write: keep the app folder so the failure is
            # reported by whoever tries to save, not swallowed here.
            logger.warning("Sin carpeta de datos escribible; se usará %s", candidate)
            _data_dir_cache = candidate
            return _data_dir_cache
        logger.info(
            "Carpeta de la aplicación no escribible (%s); datos en %s",
            candidate, fallback,
        )
        _data_dir_cache = fallback
    return _data_dir_cache


def logs_dir() -> Path:
    return data_dir() / "logs"


def reset_cache() -> None:
    """Forget the resolved data directory (tests)."""
    global _data_dir_cache
    _data_dir_cache = None
