"""Application entry point for the PySide6 UI."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Must be set before QtWebEngine/Chromium starts (Windows GPU crashes).
def _configure_webengine_env() -> None:
    extra = "--disable-gpu --disable-gpu-compositing --disable-features=DirectComposition"
    current = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
    if extra not in current:
        os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = f"{current} {extra}".strip()


_configure_webengine_env()

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ..core.config import ConfigManager
from ..core.logging_config import initialize_logging
from ..core.paths import logs_dir
from . import theme as theme_module
from .log_handler import QtLogHandler
from .main_window import MainWindow


def _resolve_app_icon() -> QIcon:
    """Return the packaged app icon, falling back to an empty QIcon."""
    candidates = []
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidates.append(Path(frozen_root) / "src" / "assets" / "branding" / "app_icon.ico")
    here = Path(__file__).resolve().parents[2]
    candidates.append(here / "src" / "assets" / "branding" / "app_icon.ico")
    for candidate in candidates:
        if candidate.is_file():
            return QIcon(str(candidate))
    return QIcon()


def _install_qt_log_handler(level: str) -> QtLogHandler:
    numeric = getattr(logging, level.upper(), logging.INFO)
    handler = QtLogHandler(numeric)
    root = logging.getLogger()
    root.addHandler(handler)
    return handler


def _set_windows_app_id(app_id: str) -> None:
    """Register a distinct AppUserModelID so Windows uses our icon in the taskbar."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError):
        pass


def main(argv: Optional[list] = None) -> int:
    argv = argv if argv is not None else sys.argv
    _set_windows_app_id("AEROSCAN.RenombradorPKS.2026")
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    app = QApplication(argv)
    app.setApplicationName("Renombrador PKS 2026")

    app_icon = _resolve_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    config_manager = ConfigManager()
    cfg = config_manager.config

    # Logs go to the data directory, not to whatever the working directory
    # happens to be when the shortcut launches the app.
    initialize_logging(log_dir=str(logs_dir()), log_level=cfg.log_level)
    log_handler = _install_qt_log_handler(cfg.log_level)

    app.setStyleSheet(theme_module.get_stylesheet(cfg.theme))

    window = MainWindow(config_manager, log_handler)
    window.show()

    logging.getLogger(__name__).info(
        "UI Qt arrancada · tema=%s · carpeta=%s · kml=%s",
        cfg.theme,
        cfg.last_folder or "—",
        cfg.last_kml or "—",
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
