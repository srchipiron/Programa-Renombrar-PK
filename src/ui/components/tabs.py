"""
Modern tabs component with improved organization.
"""
import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
from typing import List, Optional, Dict, Any
import logging
from PIL import Image, ImageTk

from .base import BaseFrame, MessageBox
from ...core.models import PhotoItem
from ...core.events import EventType, subscribe_to_event

logger = logging.getLogger(__name__)

class PreviewTab(BaseFrame):
    """Preview tab with data table and image preview."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._setup_ui()
        self._subscribe_to_events()
    
    def _setup_ui(self):
        """Setup preview tab UI."""
        self.configure(padding=10)
        
        # Main content
        content = tb.Frame(self)
        content.pack(fill=BOTH, expand=YES)
        
        # Left side - Data table
        left_frame = tb.Frame(content)
        left_frame.pack(side=LEFT, fill=BOTH, expand=YES)
        
        # Toolbar
        toolbar = tb.Frame(left_frame)
        toolbar.pack(fill=X, pady=(0, 5))
        
        self.filter_var = tk.StringVar()
        self.filter_entry = tb.Entry(
            toolbar,
            textvariable=self.filter_var,
            placeholder_text="Filtrar archivos..."
        )
        self.filter_entry.pack(side=LEFT, fill=X, expand=YES)
        self.filter_entry.bind('<KeyRelease>', self._on_filter_change)
        
        tb.Button(
            toolbar,
            text="Limpiar",
            command=self._clear_filter
        ).pack(side=RIGHT, padx=(5, 0))
        
        # Treeview
        columns = ("original", "nuevo", "pk", "distancia", "estado")
        self.tree = tb.Treeview(
            left_frame,
            columns=columns,
            show="headings",
            bootstyle=INFO
        )
        
        # Configure columns
        self.tree.heading("original", text="Archivo Original")
        self.tree.heading("nuevo", text="Nuevo Nombre")
        self.tree.heading("pk", text="Punto PK")
        self.tree.heading("distancia", text="Distancia (m)")
        self.tree.heading("estado", text="Estado")
        
        self.tree.column("original", width=250)
        self.tree.column("nuevo", width=250)
        self.tree.column("pk", width=120, anchor=CENTER)
        self.tree.column("distancia", width=100, anchor=E)
        self.tree.column("estado", width=80, anchor=CENTER)
        
        # Scrollbars
        tree_scroll_y = tb.Scrollbar(left_frame, orient=VERTICAL, command=self.tree.yview)
        tree_scroll_x = tb.Scrollbar(left_frame, orient=HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=tree_scroll_y.set, xscrollcommand=tree_scroll_x.set)
        
        # Pack treeview and scrollbars
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll_y.grid(row=0, column=1, sticky="ns")
        tree_scroll_x.grid(row=1, column=0, sticky="ew")
        
        left_frame.grid_rowconfigure(0, weight=1)
        left_frame.grid_columnconfigure(0, weight=1)
        
        # Right side - Image preview
        right_frame = tb.Frame(content)
        right_frame.pack(side=RIGHT, fill=Y, padx=(10, 0))
        
        # Preview card
        preview_card = tb.Frame(right_frame, borderwidth=1, relief="solid")
        preview_card.pack(fill=BOTH, expand=YES)
        
        # Preview header
        preview_header = tb.Frame(preview_card, padding=5)
        preview_header.pack(fill=X)
        tb.Label(
            preview_header,
            text="Vista Previa",
            font=("Segoe UI", 11, "bold")
        ).pack(side=LEFT)
        
        # Preview content
        preview_content = tb.Frame(preview_card, padding=10)
        preview_content.pack(fill=BOTH, expand=YES)
        
        # Image label
        self.preview_image_label = tb.Label(preview_content)
        self.preview_image_label.pack(pady=(0, 10))
        
        # Info labels
        self.preview_info_label = tb.Label(
            preview_content,
            text="Selecciona una imagen",
            font=("Segoe UI", 9)
        )
        self.preview_info_label.pack()
        
        # Open button
        self.open_image_btn = tb.Button(
            preview_content,
            text="Abrir Imagen",
            command=self._open_selected_image,
            state=DISABLED
        )
        self.open_image_btn.pack(pady=(10, 0))
        
        # Bind tree selection
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
    
    def _subscribe_to_events(self):
        """Subscribe to application events."""
        subscribe_to_event(EventType.PHOTOS_PROCESSED, self._on_photos_processed)
    
    def update_data(self, items: List[PhotoItem]):
        """Update treeview with new data."""
        # Clear existing data
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Add new data
        for item in items:
            status = "✓ Dentro" if item.is_inside_threshold else "✗ Fuera"
            status_tag = "inside" if item.is_inside_threshold else "outside"
            
            self.tree.insert(
                "",
                END,
                values=(
                    item.name,
                    item.new_name_base or "",
                    item.pk_display or "",
                    f"{item.distance:.2f}" if item.distance != float('inf') else "N/A",
                    status
                ),
                tags=(status_tag,)
            )
        
        # Configure tags
        self.tree.tag_configure("inside", foreground="green")
        self.tree.tag_configure("outside", foreground="red")
    
    def _on_filter_change(self, event=None):
        """Handle filter text change."""
        filter_text = self.filter_var.get().lower()
        
        for item in self.tree.get_children():
            values = self.tree.item(item)['values']
            # Search in all columns
            match = any(filter_text in str(value).lower() for value in values)
            
            if match:
                self.tree.reattach(item, "", END)
            else:
                self.tree.detach(item)
    
    def _clear_filter(self):
        """Clear filter."""
        self.filter_var.set("")
        self._on_filter_change()
    
    def _on_tree_select(self, event=None):
        """Handle tree selection."""
        selection = self.tree.selection()
        if not selection:
            self._clear_preview()
            return
        
        item = self.tree.item(selection[0])
        values = item['values']
        
        if values and values[0]:  # Original filename
            self._load_preview(values[0])
    
    def _load_preview(self, filename: str):
        """Load image preview."""
        try:
            # This would need to be connected to the actual data
            # For now, just show the filename
            self.preview_info_label.configure(text=f"Imagen: {filename}")
            self.open_image_btn.configure(state=NORMAL)
            
            # TODO: Load actual image thumbnail
            # self._load_image_thumbnail(path)
            
        except Exception as e:
            logger.error(f"Error loading preview: {e}")
            self._clear_preview()
    
    def _clear_preview(self):
        """Clear preview."""
        self.preview_image_label.configure(image="")
        self.preview_info_label.configure(text="Selecciona una imagen")
        self.open_image_btn.configure(state=DISABLED)
    
    def _open_selected_image(self):
        """Open selected image in default viewer."""
        selection = self.tree.selection()
        if selection:
            values = self.tree.item(selection[0])['values']
            if values and values[0]:
                import os
                import subprocess
                import platform
                
                # This would need the actual file path
                # For now, just log
                logger.info(f"Would open image: {values[0]}")
    
    def _on_photos_processed(self, event):
        """Handle photos processed event."""
        items = event.data.get('items', [])
        self.update_data(items)

class LogTab(BaseFrame):
    """Log tab with filtered log display."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._setup_ui()
        self._subscribe_to_events()
    
    def _setup_ui(self):
        """Setup log tab UI."""
        self.configure(padding=10)
        
        # Toolbar
        toolbar = tb.Frame(self)
        toolbar.pack(fill=X, pady=(0, 5))
        
        # Log level filter
        tb.Label(toolbar, text="Nivel:").pack(side=LEFT)
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_level_combo = tb.Combobox(
            toolbar,
            textvariable=self.log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            state="readonly",
            width=10
        )
        self.log_level_combo.pack(side=LEFT, padx=(5, 10))
        self.log_level_combo.bind('<<ComboboxSelected>>', self._on_level_change)
        
        # Clear button
        tb.Button(
            toolbar,
            text="Limpiar",
            command=self._clear_log
        ).pack(side=RIGHT)
        
        # Save button
        tb.Button(
            toolbar,
            text="Guardar",
            command=self._save_log
        ).pack(side=RIGHT, padx=(0, 5))
        
        # Log text widget
        self.log_text = ScrolledFrame(
            self,
            bootstyle=INFO,
            autohide=True
        )
        self.log_text.pack(fill=BOTH, expand=YES)
        
        # Configure text tags
        self.text_widget = self.log_text.text
        self.text_widget.configure(font=("Consolas", 9))
        
        self.text_widget.tag_configure("DEBUG", foreground="gray")
        self.text_widget.tag_configure("INFO", foreground="black")
        self.text_widget.tag_configure("WARNING", foreground="orange")
        self.text_widget.tag_configure("ERROR", foreground="red")
    
    def _subscribe_to_events(self):
        """Subscribe to application events."""
        subscribe_to_event(EventType.LOG_MESSAGE, self._on_log_message)
        subscribe_to_event(EventType.ERROR_OCCURRED, self._on_error_occurred)
    
    def add_log_message(self, level: str, message: str):
        """Add a log message to the display."""
        import datetime
        
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {level}: {message}\n"
        
        self.text_widget.insert(END, formatted_message, level)
        self.text_widget.see(END)
        
        # Limit log size
        lines = int(self.text_widget.index('end-1c').split('.')[0])
        if lines > 1000:
            self.text_widget.delete('1.0', '100.0')
    
    def _on_level_change(self, event=None):
        """Handle log level filter change."""
        # This would filter the displayed log messages
        # For now, just log the change
        logger.info(f"Log level changed to: {self.log_level_var.get()}")
    
    def _clear_log(self):
        """Clear log display."""
        self.text_widget.delete('1.0', END)
    
    def _save_log(self):
        """Save log to file."""
        from tkinter import filedialog
        
        filename = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log files", "*.log"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(self.text_widget.get('1.0', END))
                MessageBox.show_info("Éxito", "Log guardado correctamente")
            except Exception as e:
                MessageBox.show_error("Error", f"Error al guardar log: {e}")
    
    def _on_log_message(self, event):
        """Handle log message event."""
        data = event.data
        level = data.get('level', 'INFO')
        message = data.get('message', '')
        self.add_log_message(level, message)
    
    def _on_error_occurred(self, event):
        """Handle error occurred event."""
        data = event.data
        message = data.get('message', 'Error desconocido')
        self.add_log_message('ERROR', message)

class MapTab(BaseFrame):
    """Map tab for spatial visualization."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup map tab UI."""
        self.configure(padding=10)
        
        # Placeholder for map functionality
        placeholder = tb.Frame(self)
        placeholder.pack(fill=BOTH, expand=YES)
        
        tb.Label(
            placeholder,
            text="Mapa interactivo",
            font=("Segoe UI", 14, "bold")
        ).pack(expand=YES)
        
        tb.Label(
            placeholder,
            text="El mapa se mostrará aquí después de procesar las imágenes",
            font=("Segoe UI", 10)
        ).pack()

class HelpTab(BaseFrame):
    """Help tab with documentation."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup help tab UI."""
        self.configure(padding=10)
        
        # Scrollable frame for help content
        help_frame = ScrolledFrame(self, autohide=True)
        help_frame.pack(fill=BOTH, expand=YES)
        
        content = help_frame.text
        content.configure(font=("Segoe UI", 10), wrap=WORD)
        
        help_text = """
📍 RENOMBRADOR PKS - AYUDA

🚀 INICIO RÁPIDO
1. Selecciona una carpeta con imágenes
2. Carga un archivo KML/KMZ con los puntos PK
3. Ajusta el umbral de distancia
4. Haz clic en "Analizar Imágenes"
5. Revisa la vista previa
6. Procesa los cambios

📁 ARCHIVOS COMPATIBLES
• Imágenes: JPG, JPEG, PNG, TIFF, BMP
• KML/KMZ: Archivos de Google Earth
• GeoJSON: Formato de datos geoespaciales
• SRT: Subtítulos de video con coordenadas GPS

⚙️ CONFIGURACIÓN
• Umbral: Distancia máxima para considerar una imagen "dentro"
• Sufijo: Texto añadido al nombre de archivo
• Copia de seguridad: Guarda copia antes de renombrar

🗺️ FUNCIONES AVANZADAS
• Cálculo automático de umbral
• Exportación a CSV
• Generación de mapas interactivos
• Soporte para subtítulos de video

❌ ERRORES COMUNES
• "No se encontraron imágenes": Verifica que la carpeta contenga archivos de imagen válidos
• "Error en KML": Asegúrate que el archivo KML/KMZ contenga puntos y líneas válidas
• "Sin coordenadas GPS": Las imágenes deben tener datos EXIF GPS

💡 CONSEJOS
• Usa umbrales más grandes para áreas extensas
• Activa las copias de seguridad para operaciones importantes
• Filtra los resultados para encontrar archivos específicos
• Exporta a CSV para análisis en Excel

📞 SOPORTE
Para reportar problemas o solicitar mejoras, contacta al equipo de desarrollo.
        """
        
        content.insert('1.0', help_text)
        content.configure(state=DISABLED)

class ModernTabs(tb.Notebook):
    """Modern tabs component with organized sections."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.pack(side=LEFT, fill=BOTH, expand=YES, padx=(10,0))
        
        self._setup_tabs()
    
    def _setup_tabs(self):
        """Setup all tabs."""
        # Preview tab
        self.preview_tab = PreviewTab(self)
        self.add(self.preview_tab, text="📋 Vista Previa")
        
        # Map tab
        self.map_tab = MapTab(self)
        self.add(self.map_tab, text="🗺️ Mapa")
        
        # Log tab
        self.log_tab = LogTab(self)
        self.add(self.log_tab, text="📝 Registro")
        
        # Help tab
        self.help_tab = HelpTab(self)
        self.add(self.help_tab, text="❓ Ayuda")
    
    def update_preview_data(self, items: List[PhotoItem]):
        """Update preview tab with new data."""
        self.preview_tab.update_data(items)
    
    def add_log_message(self, level: str, message: str):
        """Add message to log tab."""
        self.log_tab.add_log_message(level, message)
