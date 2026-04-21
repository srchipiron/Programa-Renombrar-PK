"""
Modern sidebar component with improved organization.
"""
import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.tooltip import ToolTip
from typing import Dict, Callable, Optional
import logging

from .base import CardFrame, FileSelector, ActionButton, ToolBar
from ...core.events import EventType, subscribe_to_event
from ...core.config import ConfigManager

logger = logging.getLogger(__name__)

class ModernSidebar(ScrolledFrame):
    """Modern sidebar with organized sections."""
    
    def __init__(self, master, config_manager: ConfigManager, **kwargs):
        self.config_manager = config_manager
        self.callbacks: Dict[str, Callable] = {}
        
        super().__init__(master, **kwargs)
        self.pack(side=LEFT, fill=Y, padx=(0,0), pady=(0,0))
        
        self._setup_ui()
        self._subscribe_to_events()
    
    def _setup_ui(self):
        """Setup sidebar UI."""
        self.configure(padding=5)
        
        # Toolbar
        self.toolbar = ToolBar(self)
        
        # Files section
        self._build_files_section()
        
        # Configuration section
        self._build_config_section()
        
        # Actions section
        self._build_actions_section()
        
        # Map section
        self._build_map_section()
    
    def _build_files_section(self):
        """Build files selection section."""
        self.files_card = CardFrame(self, "📁 Archivos")
        self.files_card.pack(fill=X, pady=5)
        
        # Folder selector
        self.folder_selector = FileSelector(
            self.files_card.content,
            "Carpeta de Imágenes:",
            file_mode='folder',
            tooltip_text="Selecciona la carpeta que contiene las imágenes a procesar",
            validate_exists=True
        )
        open_btn = self.folder_selector.add_button("📂 Abrir", self._on_open_folder, bootstyle=INFO)
        ToolTip(open_btn, text="Abrir carpeta en el explorador de archivos")
        
        # KML selector
        self.kml_selector = FileSelector(
            self.files_card.content,
            "Archivo KML/KMZ:",
            file_mode='file',
            file_types=[
                ('KML/KMZ files', '*.kml *.kmz'),
                ('GeoJSON files', '*.geojson *.json'),
                ('All files', '*.*')
            ],
            tooltip_text="Archivo con los puntos kilométricos del proyecto",
            validate_exists=True
        )
    
    def _build_config_section(self):
        """Build configuration section."""
        self.config_card = CardFrame(self, "⚙️ Configuración")
        self.config_card.pack(fill=X, pady=5)
        
        # Threshold
        self.threshold_var = tk.StringVar(value=str(self.config_manager.config.threshold))
        threshold_frame = tb.Frame(self.config_card.content)
        threshold_frame.pack(fill=X, pady=2)
        
        tb.Label(threshold_frame, text="Umbral (m):").pack(side=LEFT)
        self.threshold_entry = tb.Entry(
            threshold_frame,
            textvariable=self.threshold_var,
            width=10
        )
        self.threshold_entry.pack(side=RIGHT)
        ToolTip(self.threshold_entry, 
                text="Distancia máxima (en metros) para considerar una imagen 'dentro' de la traza PK",
                bootstyle=(INFO, INVERSE))
        
        # Suffix
        self.suffix_var = tk.StringVar(value=self.config_manager.config.last_suffix)
        suffix_frame = tb.Frame(self.config_card.content)
        suffix_frame.pack(fill=X, pady=2)
        
        tb.Label(suffix_frame, text="Sufijo:").pack(side=LEFT)
        self.suffix_entry = tb.Entry(
            suffix_frame,
            textvariable=self.suffix_var
        )
        self.suffix_entry.pack(side=LEFT, fill=X, expand=YES, padx=(5, 0))
        ToolTip(self.suffix_entry,
                text="Texto que se añadirá a todos los nombres de archivo (ej: [PK]-ABR24)",
                bootstyle=(INFO, INVERSE))
        
        # Auto threshold button
        self.auto_threshold_btn = ActionButton(
            self.config_card.content,
            text="🔍 Calcular Umbral",
            command=self._on_auto_threshold,
            bootstyle=SECONDARY
        )
        self.auto_threshold_btn.pack(fill=X, pady=5)
        ToolTip(self.auto_threshold_btn,
                text="Calcula automáticamente el umbral óptimo basado en las distancias analizadas",
                bootstyle=(INFO, INVERSE))
        
        # Create backup checkbox
        self.backup_var = tk.BooleanVar(value=self.config_manager.config.create_backup)
        self.backup_check = tb.Checkbutton(
            self.config_card.content,
            text="💾 Crear copia de seguridad",
            variable=self.backup_var,
            command=self._on_backup_changed
        )
        self.backup_check.pack(anchor=W, pady=2)
        ToolTip(self.backup_check,
                text="Guarda una copia de los archivos originales antes de renombrarlos",
                bootstyle=(INFO, INVERSE))
    
    def _build_actions_section(self):
        """Build actions section."""
        self.actions_card = CardFrame(self, "🚀 Acciones")
        self.actions_card.pack(fill=X, pady=5)
        
        # Analyze button
        self.analyze_btn = ActionButton(
            self.actions_card.content,
            text="🔍 Analizar Imágenes",
            command=self._on_analyze,
            bootstyle=INFO
        )
        self.analyze_btn.pack(fill=X, pady=2)
        ToolTip(self.analyze_btn,
                text="Analiza todas las imágenes de la carpeta seleccionada (F5)",
                bootstyle=(INFO, INVERSE))
        
        # Preview button
        self.preview_btn = ActionButton(
            self.actions_card.content,
            text="👁️ Vista Previa",
            command=self._on_preview,
            bootstyle=PRIMARY
        )
        self.preview_btn.pack(fill=X, pady=2)
        ToolTip(self.preview_btn,
                text="Muestra vista previa de los cambios antes de aplicarlos (F6)",
                bootstyle=(INFO, INVERSE))
        
        # Process button
        self.process_btn = ActionButton(
            self.actions_card.content,
            text="✅ Procesar Cambios",
            command=self._on_process,
            bootstyle=SUCCESS
        )
        self.process_btn.pack(fill=X, pady=2)
        ToolTip(self.process_btn,
                text="Aplica los cambios de renombrado a todos los archivos (F7)",
                bootstyle=(INFO, INVERSE))
        
        # Cancel button (hidden initially)
        self.cancel_btn = ActionButton(
            self.actions_card.content,
            text="❌ Cancelar",
            command=self._on_cancel,
            bootstyle=DANGER
        )
        ToolTip(self.cancel_btn,
                text="Cancela la operación en curso (Esc)",
                bootstyle=(INFO, INVERSE))
        
        # Export CSV button
        self.export_btn = ActionButton(
            self.actions_card.content,
            text="📊 Exportar CSV",
            command=self._on_export_csv,
            bootstyle=SECONDARY
        )
        self.export_btn.pack(fill=X, pady=2)
        ToolTip(self.export_btn,
                text="Exporta los resultados a un archivo CSV (Ctrl+E)",
                bootstyle=(INFO, INVERSE))
    
    def _build_map_section(self):
        """Build map section."""
        self.map_card = CardFrame(self, "🗺️ Mapa")
        self.map_card.pack(fill=X, pady=5)
        
        self.map_btn = ActionButton(
            self.map_card.content,
            text="🗺️ Generar Mapa",
            command=self._on_generate_map,
            bootstyle=INFO
        )
        self.map_btn.pack(fill=X, pady=2)
        ToolTip(self.map_btn,
                text="Genera un mapa interactivo con todas las imágenes (F8)",
                bootstyle=(INFO, INVERSE))
    
    def _subscribe_to_events(self):
        """Subscribe to application events."""
        subscribe_to_event(EventType.ANALYSIS_STARTED, self._on_analysis_started)
        subscribe_to_event(EventType.ANALYSIS_COMPLETED, self._on_analysis_completed)
        subscribe_to_event(EventType.ANALYSIS_FAILED, self._on_analysis_failed)
        subscribe_to_event(EventType.RENAME_STARTED, self._on_rename_started)
        subscribe_to_event(EventType.RENAME_COMPLETED, self._on_rename_completed)
        subscribe_to_event(EventType.RENAME_FAILED, self._on_rename_failed)
    
    def register_callback(self, name: str, callback: Callable):
        """Register a callback function."""
        self.callbacks[name] = callback
    
    def get_config(self) -> Dict[str, any]:
        """Get current configuration from UI."""
        try:
            threshold = float(self.threshold_var.get())
        except ValueError:
            threshold = self.config_manager.config.threshold
        
        return {
            'folder': self.folder_selector.get(),
            'kml_file': self.kml_selector.get(),
            'threshold': threshold,
            'suffix': self.suffix_var.get(),
            'create_backup': self.backup_var.get()
        }
    
    def set_loading_state(self, loading: bool):
        """Set loading state for action buttons."""
        if loading:
            self.analyze_btn.set_loading(True, "Analizando...")
            self.process_btn.set_loading(True, "Procesando...")
            self.cancel_btn.pack(fill=X, pady=2)
            self.preview_btn.configure(state=DISABLED)
            self.export_btn.configure(state=DISABLED)
        else:
            self.analyze_btn.set_loading(False)
            self.process_btn.set_loading(False)
            self.cancel_btn.pack_forget()
            self.preview_btn.configure(state=NORMAL)
            self.export_btn.configure(state=NORMAL)
    
    def enable_actions(self, enabled: bool):
        """Enable/disable action buttons."""
        state = NORMAL if enabled else DISABLED
        self.analyze_btn.configure(state=state)
        self.preview_btn.configure(state=state)
        self.process_btn.configure(state=state)
        self.export_btn.configure(state=state)
        self.map_btn.configure(state=state)
    
    # Event handlers
    def _on_open_folder(self):
        """Handle open folder button."""
        if 'open_folder' in self.callbacks:
            self.callbacks['open_folder']()
    
    def _on_analyze(self):
        """Handle analyze button."""
        if 'analyze' in self.callbacks:
            # Update config before calling callback
            config = self.get_config()
            self.config_manager.update_config(**config)
            self.callbacks['analyze']()
    
    def _on_preview(self):
        """Handle preview button."""
        if 'preview' in self.callbacks:
            self.callbacks['preview']()
    
    def _on_process(self):
        """Handle process button."""
        if 'process' in self.callbacks:
            config = self.get_config()
            self.config_manager.update_config(**config)
            self.callbacks['process']()
    
    def _on_cancel(self):
        """Handle cancel button."""
        if 'cancel' in self.callbacks:
            self.callbacks['cancel']()
    
    def _on_export_csv(self):
        """Handle export CSV button."""
        if 'export_csv' in self.callbacks:
            self.callbacks['export_csv']()
    
    def _on_generate_map(self):
        """Handle generate map button."""
        if 'generate_map' in self.callbacks:
            self.callbacks['generate_map']()
    
    def _on_auto_threshold(self):
        """Handle auto threshold calculation."""
        if 'auto_threshold' in self.callbacks:
            self.callbacks['auto_threshold']()
    
    def _on_backup_changed(self):
        """Handle backup checkbox change."""
        self.config_manager.set_setting('create_backup', self.backup_var.get())
    
    # Event subscribers
    def _on_analysis_started(self, event):
        """Handle analysis started event."""
        self.set_loading_state(True)
    
    def _on_analysis_completed(self, event):
        """Handle analysis completed event."""
        self.set_loading_state(False)
        items = event.data.get('items', [])
        self.enable_actions(len(items) > 0)
    
    def _on_analysis_failed(self, event):
        """Handle analysis failed event."""
        self.set_loading_state(False)
        self.enable_actions(False)
    
    def _on_rename_started(self, event):
        """Handle rename started event."""
        self.set_loading_state(True)
    
    def _on_rename_completed(self, event):
        """Handle rename completed event."""
        self.set_loading_state(False)
    
    def _on_rename_failed(self, event):
        """Handle rename failed event."""
        self.set_loading_state(False)
