"""
Modern main window with improved architecture.
"""
import os
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import csv
from typing import List, Dict, Any
import logging

import ttkbootstrap as tb
from ttkbootstrap.constants import *

from ..core.config import ConfigManager
from ..core.logging_config import initialize_logging, get_logger
from ..core.events import EventType, get_event_manager, emit_event
from ..core.services import PhotoProcessingService, RenamingService
from ..core.models import PhotoItem
from .components.sidebar import ModernSidebar
from .components.tabs import ModernTabs
from .components.base import MessageBox, StatusBar

logger = get_logger(__name__)

class Application:
    """Main application controller."""
    
    def __init__(self):
        # Initialize logging first
        initialize_logging()
        
        # Initialize configuration
        self.config_manager = ConfigManager()
        
        # Initialize services
        self.photo_service = PhotoProcessingService(self.config_manager)
        self.renaming_service = RenamingService(self.config_manager)
        
        # Data storage
        self.processed_items: List[PhotoItem] = []
        
        # Initialize UI
        self._setup_ui()
        self._setup_callbacks()
        
        # Load last configuration
        self._load_last_config()
        
        logger.info("Application initialized successfully")
    
    def _setup_ui(self):
        """Setup the main UI."""
        # Create main window
        self.window = tb.Window(themename="darkly")
        self.window.title("📍 Renombrador PKS - Sistema Avanzado")
        self.window.geometry("1400x900")
        self.window.minsize(1200, 800)
        self._center_window()
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create main container
        main_container = tb.Frame(self.window)
        main_container.pack(fill=BOTH, expand=YES)
        
        # Create sidebar
        self.sidebar = ModernSidebar(
            main_container,
            self.config_manager,
            width=350
        )
        
        # Create tabs area
        self.tabs = ModernTabs(main_container)
        
        # Create status bar
        self.status_bar = StatusBar(self.window)
        
        # Setup window close handler
        self.window.protocol("WM_DELETE_WINDOW", self._on_closing)
        
        # Setup keyboard shortcuts
        self._setup_keyboard_shortcuts()
    
    def _create_menu_bar(self):
        """Create application menu bar."""
        menubar = tk.Menu(self.window)
        self.window.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="📁 Archivo", menu=file_menu)
        file_menu.add_command(label="Abrir Carpeta...", command=self._open_folder_dialog, accelerator="Ctrl+O")
        file_menu.add_command(label="Abrir KML...", command=self._open_kml_dialog, accelerator="Ctrl+K")
        file_menu.add_separator()
        file_menu.add_command(label="Exportar CSV...", command=self._export_to_csv, accelerator="Ctrl+E")
        file_menu.add_separator()
        file_menu.add_command(label="Salir", command=self._on_closing, accelerator="Alt+F4")
        
        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="🛠️ Herramientas", menu=tools_menu)
        tools_menu.add_command(label="Analizar Imágenes", command=self._analyze_photos, accelerator="F5")
        tools_menu.add_command(label="Vista Previa", command=self._preview_changes, accelerator="F6")
        tools_menu.add_command(label="Procesar Cambios", command=self._process_changes, accelerator="F7")
        tools_menu.add_separator()
        tools_menu.add_command(label="Generar Mapa", command=self._generate_map, accelerator="F8")
        tools_menu.add_separator()
        tools_menu.add_command(label="Cancelar Operación", command=self._cancel_operation, accelerator="Esc")
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="❓ Ayuda", menu=help_menu)
        help_menu.add_command(label="Ver Ayuda", command=self._show_help, accelerator="F1")
        help_menu.add_command(label="Acerca de", command=self._show_about)
    
    def _setup_keyboard_shortcuts(self):
        """Setup keyboard shortcuts."""
        self.window.bind("<Control-o>", lambda e: self._open_folder_dialog())
        self.window.bind("<Control-k>", lambda e: self._open_kml_dialog())
        self.window.bind("<Control-e>", lambda e: self._export_to_csv())
        self.window.bind("<F5>", lambda e: self._analyze_photos())
        self.window.bind("<F6>", lambda e: self._preview_changes())
        self.window.bind("<F7>", lambda e: self._process_changes())
        self.window.bind("<F8>", lambda e: self._generate_map())
        self.window.bind("<Escape>", lambda e: self._cancel_operation())
        self.window.bind("<F1>", lambda e: self._show_help())
    
    def _open_folder_dialog(self):
        """Open folder dialog."""
        from tkinter import filedialog
        folder = filedialog.askdirectory()
        if folder:
            self.sidebar.folder_selector.set(folder)
            self.config_manager.set_setting('last_folder', folder)
    
    def _open_kml_dialog(self):
        """Open KML file dialog."""
        from tkinter import filedialog
        file = filedialog.askopenfilename(
            filetypes=[
                ('KML/KMZ files', '*.kml *.kmz'),
                ('GeoJSON files', '*.geojson *.json'),
                ('All files', '*.*')
            ]
        )
        if file:
            self.sidebar.kml_selector.set(file)
            self.config_manager.set_setting('last_kml', file)
    
    def _show_help(self):
        """Show help tab."""
        self.tabs.select(3)  # Help tab index
    
    def _show_about(self):
        """Show about dialog."""
        MessageBox.show_info(
            "Acerca de",
            "📍 Renombrador PKS - Sistema Avanzado\n\n"
            "Versión 2.0\n"
            "Desarrollado para AEROSCAN\n\n"
            "Sistema de renombrado de imágenes aéreas\n"
            "basado en puntos kilométricos (PK)."
        )
    
    def _setup_callbacks(self):
        """Setup callback functions."""
        callbacks = {
            'open_folder': self._open_folder,
            'analyze': self._analyze_photos,
            'preview': self._preview_changes,
            'process': self._process_changes,
            'cancel': self._cancel_operation,
            'export_csv': self._export_to_csv,
            'generate_map': self._generate_map,
            'auto_threshold': self._calculate_auto_threshold
        }
        
        for name, callback in callbacks.items():
            self.sidebar.register_callback(name, callback)
    
    def _load_last_config(self):
        """Load last used configuration."""
        config = self.config_manager.config
        
        if config.last_folder:
            self.sidebar.folder_selector.set(config.last_folder)
        
        if config.last_kml:
            self.sidebar.kml_selector.set(config.last_kml)
        
        self.sidebar.threshold_var.set(str(config.threshold))
        self.sidebar.suffix_var.set(config.last_suffix)
        self.sidebar.backup_var.set(config.create_backup)
    
    def _center_window(self):
        """Center window on screen."""
        self.window.update_idletasks()
        width = self.window.winfo_width()
        height = self.window.winfo_height()
        x = (self.window.winfo_screenwidth() // 2) - (width // 2)
        y = (self.window.winfo_screenheight() // 2) - (height // 2)
        self.window.geometry(f'{width}x{height}+{x}+{y}')
    
    def run(self):
        """Run the application."""
        try:
            self.window.mainloop()
        except Exception as e:
            logger.error(f"Application error: {e}")
            MessageBox.show_error("Error", f"Error en la aplicación: {e}")
        finally:
            self._cleanup()
    
    def _on_closing(self):
        """Handle window closing."""
        try:
            # Save current configuration
            config = self.sidebar.get_config()
            self.config_manager.update_config(**config)
            
            # Stop event manager
            get_event_manager().stop()
            
            # Close window
            self.window.destroy()
            
        except Exception as e:
            logger.error(f"Error closing application: {e}")
            self.window.destroy()
    
    def _cleanup(self):
        """Cleanup resources."""
        try:
            get_event_manager().stop()
        except Exception:
            pass
    
    # Callback implementations
    def _open_folder(self):
        """Open selected folder in file explorer."""
        folder = self.sidebar.folder_selector.get()
        if folder and os.path.exists(folder):
            os.startfile(folder)
    
    def _analyze_photos(self):
        """Analyze photos in selected folder."""
        config = self.sidebar.get_config()
        
        if not config['folder']:
            MessageBox.show_warning("Advertencia", "Por favor selecciona una carpeta de imágenes")
            return
        
        if not config['kml_file']:
            MessageBox.show_warning("Advertencia", "Por favor selecciona un archivo KML/KMZ")
            return
        
        # Run analysis in separate thread
        threading.Thread(
            target=self._run_analysis,
            args=(config,),
            daemon=True
        ).start()
    
    def _run_analysis(self, config: Dict[str, Any]):
        """Run photo analysis in background thread."""
        try:
            # Load KML file
            if not self.photo_service.load_kml_file(config['kml_file']):
                return
            
            # Process folder
            items = self.photo_service.process_folder(config['folder'])
            
            # Update UI
            self.processed_items = items
            self.tabs.update_preview_data(items)
            
            # Update status
            if items:
                inside_count = sum(1 for item in items if item.is_inside_threshold)
                self.status_bar.set_status(
                    f"Análisis completado: {inside_count}/{len(items)} imágenes dentro del umbral"
                )
                self.status_bar.set_count(len(items))
            else:
                self.status_bar.set_status("No se encontraron imágenes válidas")
                self.status_bar.set_count(0)
            
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            MessageBox.show_error("Error", f"Error en el análisis: {e}")
    
    def _preview_changes(self):
        """Preview renaming changes."""
        if not self.processed_items:
            MessageBox.show_info("Información", "No hay imágenes procesadas para previsualizar")
            return
        
        # Switch to preview tab
        self.tabs.select(0)  # Preview tab index
        
        # Update preview with current configuration
        config = self.sidebar.get_config()
        self._update_preview_names(config['suffix'])
    
    def _update_preview_names(self, suffix: str):
        """Update preview names with current suffix."""
        for item in self.processed_items:
            if item.pk_display:
                _, ext = os.path.splitext(item.name)
                ext = ext or ".jpg"
                if item.is_inside_threshold:
                    item.new_name_base = f"{item.pk_display}_{suffix}{ext}"
                else:
                    item.new_name_base = f"FUERA_{item.pk_display}_{suffix}{ext}"
        
        self.tabs.update_preview_data(self.processed_items)
    
    def _process_changes(self):
        """Process file renaming."""
        if not self.processed_items:
            MessageBox.show_info("Información", "No hay imágenes procesadas para renombrar")
            return
        
        # Confirm operation
        result = MessageBox.ask_yesno(
            "Confirmar",
            f"¿Estás seguro de renombrar {len(self.processed_items)} archivos?\n\n"
            "Esta acción modificará los nombres de archivo originales."
        )
        
        if not result:
            return
        
        # Run renaming in separate thread
        threading.Thread(
            target=self._run_renaming,
            daemon=True
        ).start()
    
    def _run_renaming(self):
        """Run file renaming in background thread."""
        try:
            config = self.sidebar.get_config()
            results = self.renaming_service.rename_files(
                self.processed_items,
                config['suffix']
            )
            
            # Update UI with results
            success_count = len(results.get('success', []))
            failed_count = len(results.get('failed', []))
            skipped_count = len(results.get('skipped', []))
            
            message = f"Renombrado completado:\n"
            message += f"✓ Éxito: {success_count}\n"
            message += f"✗ Fallidos: {failed_count}\n"
            message += f"⚠ Omitidos: {skipped_count}"
            
            if failed_count > 0:
                MessageBox.show_warning("Proceso Completado", message)
            else:
                MessageBox.show_info("Proceso Completado", message)
            
            # Update preview
            self.tabs.update_preview_data(self.processed_items)
            
        except Exception as e:
            logger.error(f"Renaming error: {e}")
            MessageBox.show_error("Error", f"Error en el renombrado: {e}")
    
    def _cancel_operation(self):
        """Cancel current operation."""
        try:
            self.photo_service.cancel_processing()
            self.renaming_service.cancel_renaming()
            self.status_bar.set_status("Operación cancelada")
        except Exception as e:
            logger.error(f"Cancel error: {e}")
    
    def _export_to_csv(self):
        """Export results to CSV file."""
        if not self.processed_items:
            MessageBox.show_info("Información", "No hay datos para exportar")
            return
        
        # Ask for save location
        filename = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Guardar resultados como CSV"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'original', 'nuevo', 'pk', 'distancia', 'latitud', 
                    'longitud', 'estado', 'fecha', 'hora'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for item in self.processed_items:
                    writer.writerow({
                        'original': item.name,
                        'nuevo': item.new_name_base or '',
                        'pk': item.pk_display or '',
                        'distancia': f"{item.distance:.2f}" if item.distance != float('inf') else 'N/A',
                        'latitud': f"{item.lat:.6f}",
                        'longitud': f"{item.lon:.6f}",
                        'estado': 'Dentro' if item.is_inside_threshold else 'Fuera',
                        'fecha': item.date_str,
                        'hora': item.time_str
                    })
            
            MessageBox.show_info("Éxito", f"Datos exportados a {filename}")
            
        except Exception as e:
            logger.error(f"Export error: {e}")
            MessageBox.show_error("Error", f"Error al exportar: {e}")
    
    def _generate_map(self):
        """Generate interactive map."""
        if not self.processed_items:
            MessageBox.show_info("Información", "No hay datos para generar mapa")
            return
        
        try:
            # Import map manager (avoid circular import)
            from ..map_component import MapManager
            
            config = self.sidebar.get_config()
            
            # Prepare data for map
            points_data = []
            for item in self.processed_items:
                points_data.append({
                    'path': item.path,
                    'name': item.name,
                    'lat': item.lat,
                    'lon': item.lon,
                    'distance': item.distance,
                    'pk': item.pk_display
                })
            
            # Generate map
            MapManager.generate_and_open_map(
                points_data,
                [],  # KML coords - would need from spatial calculator
                config['threshold'],
                config['folder'],
                []  # KML points - would need from spatial calculator
            )
            
            MessageBox.show_info("Éxito", "Mapa generado y abierto en navegador")
            
        except Exception as e:
            logger.error(f"Map generation error: {e}")
            MessageBox.show_error("Error", f"Error al generar mapa: {e}")
    
    def _calculate_auto_threshold(self):
        """Calculate automatic threshold based on data distribution."""
        if not self.processed_items:
            MessageBox.show_info("Información", "No hay datos para calcular umbral")
            return
        
        try:
            # Calculate distances
            distances = [item.distance for item in self.processed_items 
                        if item.distance != float('inf')]
            
            if not distances:
                MessageBox.show_warning("Advertencia", "No hay distancias válidas para calcular")
                return
            
            # Calculate statistics
            import statistics
            mean_dist = statistics.mean(distances)
            stdev_dist = statistics.stdev(distances) if len(distances) > 1 else 0
            
            # Calculate threshold (mean + 2*stdev)
            auto_threshold = mean_dist + (2 * stdev_dist)
            
            # Update UI
            self.sidebar.threshold_var.set(f"{auto_threshold:.1f}")
            
            MessageBox.show_info(
                "Umbral Calculado",
                f"Umbral automático: {auto_threshold:.1f}m\n"
                f"Basado en {len(distances)} mediciones\n"
                f"Media: {mean_dist:.1f}m, Desv. Est.: {stdev_dist:.1f}m"
            )
            
        except Exception as e:
            logger.error(f"Auto threshold error: {e}")
            MessageBox.show_error("Error", f"Error al calcular umbral: {e}")

def main():
    """Main entry point."""
    try:
        app = Application()
        app.run()
    except Exception as e:
        print(f"Fatal error: {e}")
        messagebox.showerror("Error Fatal", f"No se pudo iniciar la aplicación: {e}")

if __name__ == "__main__":
    main()
