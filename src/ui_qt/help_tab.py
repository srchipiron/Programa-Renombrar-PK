"""Help tab rendered from a rich HTML document."""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

from ..core.version import version_line

_HELP_HTML = """
<style>
body { font-family: 'Segoe UI', Inter, sans-serif; padding: 8px 14px; }
h2 { color: #3b82f6; margin-bottom: 4px; }
h3 { color: #a78bfa; margin-top: 16px; }
kbd {
  background: #1e293b; color: #e6edf3; border: 1px solid #334155;
  padding: 1px 6px; border-radius: 4px; font-family: 'Fira Code', monospace;
  font-size: 12px;
}
li { margin-bottom: 4px; }
</style>
<h2>{titulo}</h2>
<p>Herramienta para renombrar fotografías aéreas a partir de un archivo KML/KMZ/GeoJSON con la traza y los puntos kilométricos del proyecto.</p>

<h3>Flujo recomendado</h3>
<ol>
  <li>Selecciona la carpeta de imágenes y el archivo de la traza. El botón <b>Analizar</b> se habilita solo cuando ambos son válidos.</li>
  <li>Pulsa <b>Analizar</b> (F5): extrae EXIF GPS, calcula distancias y <b>aplica el umbral automático</b> a la vista previa.</li>
  <li>Si hace falta, afina el umbral a mano o pulsa <b>Calcular umbral automáticamente</b> de nuevo — la vista previa se actualiza sola (o <kbd>F6</kbd>).</li>
  <li>Revisa la tabla (miniatura, PK y nuevo nombre). Filtra por estado si es necesario.</li>
  <li>Pulsa <b>Procesar</b> (F7) para renombrar. Activa la copia de seguridad si quieres un fallback físico.</li>
  <li>Si necesitas revertir, usa <b>Deshacer renombrado</b> (historial interno o CSV) o
      <b>Historial…</b> (Ctrl+H) para operaciones anteriores.</li>
</ol>

<h3>Placeholders de plantilla</h3>
<ul>
  <li><code>[PK]</code>: Punto kilométrico asociado.</li>
  <li><code>[ORIG]</code>: Nombre original sin extensión.</li>
  <li><code>[FECHA]</code>, <code>[HORA]</code>: Metadatos EXIF.</li>
</ul>

<h3>Atajos de teclado</h3>
<ul>
  <li><kbd>F5</kbd> Analizar</li>
  <li><kbd>F6</kbd> Actualizar vista previa</li>
  <li><kbd>F7</kbd> Procesar</li>
  <li><kbd>F8</kbd> Generar mapa</li>
  <li><kbd>Ctrl</kbd>+<kbd>O</kbd> Abrir carpeta</li>
  <li><kbd>Ctrl</kbd>+<kbd>K</kbd> Seleccionar KML</li>
  <li><kbd>Ctrl</kbd>+<kbd>E</kbd> Exportar CSV</li>
  <li><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>E</kbd> Exportar GeoJSON (fotos + huecos de cobertura)</li>
  <li><kbd>Ctrl</kbd>+<kbd>H</kbd> Historial de renombrados</li>
  <li><kbd>Ctrl</kbd>+<kbd>T</kbd> Alternar tema claro/oscuro</li>
  <li><kbd>Esc</kbd> Cancelar la operación en curso</li>
  <li><kbd>F1</kbd> Mostrar esta ayuda</li>
</ul>

<h3>Cadena calibrada y cobertura</h3>
<ul>
  <li>El umbral mide la <b>distancia perpendicular a la traza</b> (corredor), no al PK más cercano. Los landmarks (vertederos) siguen usando distancia al placemark.</li>
  <li>Los nombres usan el <b>PK interpolado</b> entre anclas oficiales del KML (p. ej. <code>10+500</code>), no un snap al hito más cercano.</li>
  <li>Tras analizar, la barra de estado resume la cobertura y los huecos ≥ 100 m. El CSV y el GeoJSON incluyen esos huecos.</li>
</ul>

<h3>Notas</h3>
<ul>
  <li>La copia de seguridad se guarda en <code>_backup_originales</code> dentro de la carpeta raíz.</li>
  <li>El reporte de renombrado se escribe en <code>reporte_renombrado.csv</code>.</li>
  <li>El umbral automático combina IQR y percentil 90 y se acota entre 10 m y 250 m.</li>
</ul>
"""


class HelpTab(QWidget):
    """Render the help document in a ``QTextBrowser`` widget."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        # La version viaja en la ayuda: una captura de pantalla basta para
        # saber que build esta ejecutando el operador.
        self.browser.setHtml(_HELP_HTML.replace("{titulo}", version_line()))
        layout.addWidget(self.browser)
