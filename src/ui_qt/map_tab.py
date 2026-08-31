"""Embedded interactive map tab."""
from __future__ import annotations

import logging
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QUrl, Signal, Slot
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..map_component import MapManager

logger = logging.getLogger(__name__)

_PLACEHOLDER_HTML = (
    "<html><body style='background:#0f172a;color:#94a3b8;font-family:Segoe UI;"
    "display:flex;align-items:center;justify-content:center;height:100%;'>"
    "<h2>Sin datos cargados</h2></body></html>"
)


class _LoggingWebPage(QWebEnginePage):
    """QWebEnginePage that forwards JS console output to the Python logger."""

    _LEVEL_MAP = {
        QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: logging.INFO,
        QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: logging.WARNING,
        QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: logging.ERROR,
    }

    def javaScriptConsoleMessage(self, level, message, line_number, source_id):  # noqa: N802, D401
        log_level = self._LEVEL_MAP.get(level, logging.INFO)
        logger.log(
            log_level,
            "WebEngine JS [%s:%s] %s",
            os.path.basename(source_id or "<mapa>"),
            line_number,
            message,
        )


class MapTab(QWidget):
    """Tab that hosts an embedded :class:`QWebEngineView` for the map.

    The WebEngine view is created lazily on first use so startup stays stable
    on Windows machines where Chromium GPU init can crash the process.
    """

    reload_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.info_label = QLabel("Carga fotos y pulsa 'Generar mapa' para ver la cartografía.")
        self.info_label.setStyleSheet("color: #94a3b8;")
        toolbar.addWidget(self.info_label, 1)

        self.reload_btn = QPushButton("Recargar")
        self.reload_btn.clicked.connect(self.reload_requested)
        toolbar.addWidget(self.reload_btn)

        self.open_browser_btn = QPushButton("Abrir en navegador")
        self.open_browser_btn.setToolTip("Abre una copia del mapa en el navegador del sistema")
        self.open_browser_btn.clicked.connect(self._open_in_browser)
        self.open_browser_btn.setEnabled(False)
        toolbar.addWidget(self.open_browser_btn)

        layout.addLayout(toolbar)

        self._view_host = QWidget()
        self._view_layout = QVBoxLayout(self._view_host)
        self._view_layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel(
            "El mapa interactivo se cargará aquí cuando pulses «Generar mapa» (F8)."
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color: #94a3b8; padding: 24px;")
        self._view_layout.addWidget(self._placeholder)
        layout.addWidget(self._view_host, 1)

        self._view: Optional[QWebEngineView] = None
        self._page: Optional[_LoggingWebPage] = None
        self._last_html_path: Optional[str] = None

    def _ensure_view(self) -> QWebEngineView:
        if self._view is not None:
            return self._view

        logger.info("Initializing embedded WebEngine view (lazy)")
        self._placeholder.hide()

        self._view = QWebEngineView()
        self._page = _LoggingWebPage(self._view)
        self._view.setPage(self._page)

        settings = self._view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)

        self._view.loadFinished.connect(self._on_load_finished)
        self._view.setHtml(_PLACEHOLDER_HTML)
        self._view_layout.addWidget(self._view)
        return self._view

    # ------------------------------------------------------------------
    def render_points(
        self,
        points: List[dict],
        kml_coords: List[list],
        kml_points: List[dict],
        threshold: float,
    ) -> None:
        """Build the HTML and load it into the embedded web view."""
        view = self._ensure_view()
        try:
            html = MapManager.build_map_html(points, kml_coords, threshold, kml_points)
        except Exception as exc:
            logger.exception("Failed to build map HTML")
            view.setHtml(
                f"<html><body style='color:#ef4444;padding:20px;font-family:Segoe UI;'>"
                f"Error generando el mapa: {exc}</body></html>"
            )
            self.open_browser_btn.setEnabled(False)
            return

        # Each render used to leave its file behind for good: six orphans of
        # the old size were sitting in %TEMP%, and with the embedded
        # thumbnails each one is now megabytes.
        self._discard_previous_html()
        fd, path = tempfile.mkstemp(suffix=".html", prefix="visor_pks_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError:
            logger.exception("Unable to write map temp file")
            view.setHtml(html, QUrl("https://local.map/"))
            self._last_html_path = None
            self.open_browser_btn.setEnabled(False)
            return

        self._last_html_path = path
        url = QUrl.fromLocalFile(path)
        logger.info("Loading embedded map from %s", url.toString())
        view.load(url)
        self.info_label.setText(
            f"Mostrando {len(points)} fotos (umbral {threshold:.1f} m)."
        )
        self.open_browser_btn.setEnabled(True)

    @Slot(bool)
    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            logger.info("Embedded map loaded successfully")
        else:
            logger.error(
                "Embedded map failed to load. Comprueba conexión a internet "
                "(el mapa descarga tiles desde la red)."
            )
            self.info_label.setText(
                "No se pudo cargar el mapa embebido. Revisa tu conexión o usa "
                "'Abrir en navegador'."
            )

    def _discard_previous_html(self) -> None:
        """Remove the temp file of the previous render, if any."""
        previous = self._last_html_path
        self._last_html_path = None
        if not previous:
            return
        try:
            os.remove(previous)
        except OSError as exc:
            logger.debug("No se pudo borrar el mapa temporal %s: %s", previous, exc)

    @Slot()
    def _open_in_browser(self) -> None:
        if not self._last_html_path:
            return
        # as_uri() percent-encodes: a user profile with a space in it produced
        # a malformed file:/// URL when built by hand.
        webbrowser.open(Path(self._last_html_path).as_uri())

    def focus_photo(self, photo_name_or_path: str) -> None:
        """Centra y abre el popup del marcador correspondiente a una foto."""
        if self._view is not None and photo_name_or_path:
            clean_name = os.path.basename(photo_name_or_path).replace("\\", "\\\\").replace("'", "\\'")
            js = f"if (window.focusPhoto) {{ window.focusPhoto('{clean_name}'); }}"
            self._view.page().runJavaScript(js)

