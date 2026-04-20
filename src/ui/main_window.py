import os
import json
import tkinter as tk
from tkinter import filedialog, messagebox
import threading
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import csv
from PIL import ImageGrab

from src.core.spatial_calculator import SpatialCalculator
from src.core.renamer_logic import RenamerLogic
from src.core.video_extractor import VideoExtractor
from src.core.models import PhotoItem

from src.ui.sidebar import SidebarPanel
from src.ui.tabs import TabsPanel

CONFIG_FILE = "config.json"

class MainWindow(tb.Window):
    def __init__(self):
        super().__init__(themename="darkly")
        self.title("📍 Renombrador PKS Febrero 2026")
        self.geometry("1200x800")
        self.minsize(1000, 700)
        self._center_window()
        
        self.spatial_calc = SpatialCalculator()
        self.renamer = RenamerLogic(self.spatial_calc)
        self.video_extractor = VideoExtractor()
        
        self.vars = {
            'folder': tk.StringVar(),
            'kml': tk.StringVar(),
            'suffix': tk.StringVar(),
            'threshold': tk.DoubleVar(value=30.0),
            'backup': tk.BooleanVar(value=True)
        }
        
        self.image_data = [] # List[PhotoItem]
        self.stats_data = {}
        
        self.is_processing = False
        self.cancel_requested = False
        
        self.load_config()
        self._build_ui()
        self.tabs.insert_log("Aplicación modular iniciada con éxito.", "success")
        
    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f'+{x}+{y}')

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    conf = json.load(f)
                    self.vars['folder'].set(conf.get("last_folder", ""))
                    self.vars['kml'].set(conf.get("last_kml", ""))
                    self.vars['suffix'].set(conf.get("last_suffix", ""))
                    self.vars['threshold'].set(conf.get("threshold", 30.0))
                    self.vars['backup'].set(conf.get("create_backup", True))
            except: pass

    def save_config(self):
        conf = {
            "last_folder": self.vars['folder'].get(),
            "last_kml": self.vars['kml'].get(),
            "last_suffix": self.vars['suffix'].get(),
            "threshold": self.vars['threshold'].get(),
            "create_backup": self.vars['backup'].get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f: json.dump(conf, f, indent=4)
        except: pass

    def _build_ui(self):
        header = tb.Frame(self, padding=10)
        header.pack(fill=X)
        tb.Label(header, text="📍 Renombrador PKS Febrero 2026", font=("Segoe UI", 20, "bold"), foreground="#3498db").pack(side=LEFT)
        self.status_lbl = tb.Label(header, text="● Listo", font=("Segoe UI", 12), foreground="#2ecc71")
        self.status_lbl.pack(side=RIGHT)

        body = tb.Frame(self)
        body.pack(fill=BOTH, expand=YES, padx=10, pady=5)
        
        callbacks = {
            'select_folder': self.select_folder,
            'open_folder': self.open_selected_folder,
            'select_kml': self.select_kml,
            'select_srt': self.select_srt,
            'analyze': self.start_analysis,
            'auto_threshold': self.auto_threshold,
            'preview': self.generate_preview,
            'export_csv': self.export_preview_csv,
            'process': self.confirm_and_process,
            'undo': self.confirm_and_restore,
            'cancel': self.cancel_operation,
            'open_map': self.open_map
        }
        
        self.sidebar = SidebarPanel(body, callbacks, self.vars, width=380)
        self.tabs = TabsPanel(body)
        
        if hasattr(self.tabs, 'map_filter_var'):
            self.tabs.map_filter_var.trace_add("write", lambda *args: self.apply_map_filter())
            
        if hasattr(self.tabs, 'btn_snapshot'):
            self.tabs.btn_snapshot.config(command=self.export_map_pdf)
        
        footer = tb.Frame(self, padding=10)
        footer.pack(fill=X, side=BOTTOM)
        self.stats_lbl = tb.Label(footer, text="Archivos: 0 | En umbral: 0", font=("Segoe UI", 10))
        self.stats_lbl.pack(side=LEFT)
        self.progress = tb.Progressbar(footer, mode='determinate', length=300)
        self.progress.pack(side=RIGHT)

    def log(self, msg: str, level="info"):
        self.after(0, lambda: self.tabs.insert_log(msg, level))

    def select_folder(self):
        d = filedialog.askdirectory()
        if d: self.vars['folder'].set(d); self.save_config()

    def open_selected_folder(self):
        d = self.vars['folder'].get()
        if d and os.path.exists(d): os.startfile(d)

    def select_kml(self):
        f = filedialog.askopenfilename(filetypes=[("Geoespaciales", "*.kml;*.kmz;*.geojson;*.json"), ("KML/KMZ", "*.kml;*.kmz"), ("GeoJSON", "*.geojson;*.json")])
        if f: self.vars['kml'].set(f); self.save_config()

    def select_srt(self):
        f = filedialog.askopenfilename(filetypes=[("Subtítulos Telemetría", "*.srt")])
        if not f: return
        
        self.log(f"Cargando SRT de Vuelo DJI/Autel: {os.path.basename(f)}...", "info")
        
        def _load_srt():
            self.update_ui_state(True)
            self.tabs.clear_preview()
            self.tabs.select(1) # Pestaña log
            
            # Reutilizamos image_data pero con fotogramas artificiales del video
            self.image_data = self.video_extractor.parse_srt(f)
            
            self.after(0, self._on_srt_loaded)
            
        threading.Thread(target=_load_srt, daemon=True).start()
        
    def _on_srt_loaded(self):
        self.update_ui_state(False)
        if not self.image_data:
            self.log("No se encontraron coordenadas GPS en este formato SRT.", "error")
            return
            
        self.log(f"¡Éxito! Generados {len(self.image_data)} puntos desde el vídeo.", "success")
        self.stats_lbl.config(text=f"Vídeo Cargado: {len(self.image_data)} frames lat/long")
        # Ahora el usuario podría darle al botón "Analizar" normal y 
        # se cruzarían estos fotogramas artificiales contra su red KML

    def update_ui_state(self, processing: bool):
        self.is_processing = processing
        self.sidebar.set_state(processing, bool(self.image_data))
        
        if processing:
            self.status_lbl.config(text="● Procesando...", foreground="#f39c12")
        else:
            self.status_lbl.config(text="● Listo", foreground="#2ecc71")

    def start_analysis(self):
        fld, kml = self.vars['folder'].get(), self.vars['kml'].get()
        if not os.path.isdir(fld): return messagebox.showerror("Error", "Carpeta inválida.")
        if not os.path.isfile(kml): return messagebox.showerror("Error", "Archivo Geoespacial inválido.")
            
        self.update_ui_state(True)
        self.cancel_requested = False
        self.progress['value'] = 0
        self.tabs.clear_preview()
        self.image_data = []
        self.tabs.select(1)
        
        threading.Thread(target=self._analysis_task, args=(fld, kml), daemon=True).start()

    def _analysis_task(self, folder, kml):
        try:
            self.log(f"Cargando matriz geoespacial desde {os.path.basename(kml)}...")
            self.spatial_calc.load_kml(kml)
            
            pts = len(self.spatial_calc.named_points)
            if pts: self.log(f"Matriz cargada: {pts} PKs extraídos.", "success")
            else: self.log("Adviso: No se extrajeron PKs con etiqueta clara.", "warning")
                
            def prog_cb(c, t, m):
                def up():
                    self.progress['maximum'] = t; self.progress['value'] = c
                    if c % max(1, t//20) == 0: self.tabs.insert_log(m, "info")
                self.after(0, up)

            self.log("Identificando espectro y vectores EXIF...")
            stats = self.renamer.analyze_distance_stats(folder, prog_cb)
            
            if self.cancel_requested:
                self.log("Operación interrumpida.", "warning")
                self.after(0, lambda: self.update_ui_state(False))
                return
                
            self.image_data = stats['items']
            self.stats_data = stats
            
            self.log(f"Escaneo profundo completado: {len(self.image_data)} ítems validados.", "success")
            self.log(f"Dispersión [ Min: {stats['min']:.1f}m - Max: {stats['max']:.1f}m ]")
            
            self.after(0, self._analysis_done)
        except Exception as e:
            self.log(f"Excepción en core: {e}", "error")
            self.after(0, lambda: self.update_ui_state(False))

    def _analysis_done(self):
        self.update_ui_state(False)
        self.generate_preview()
        self.tabs.select(0)

    def auto_threshold(self):
        if not self.stats_data: return
        s = self.stats_data['suggested']
        self.vars['threshold'].set(round(s, 2))
        self.log(f"Umbral calibrado a {s:.2f}m vía red {self.stats_data['method']}", "success")
        self.generate_preview()

    def generate_preview(self):
        self.tabs.clear_preview()
        self.save_config()
        
        th = self.vars['threshold'].get()
        suf = self.vars['suffix'].get()
        
        valid_items = self.renamer.build_preview_names(self.image_data, th, suf)
        items_inside = [i for i in valid_items if i.is_inside_threshold]
        
        for item in items_inside:
            self.tabs.insert_preview_row(item.name, item.new_name_base + ".jpg", item.pk_display, item.distance)
                
        t_len = len(self.image_data)
        in_len = len(items_inside)
        self.stats_lbl.config(text=f"Total: {t_len} | GPS Validado: {t_len} | Activos (<{th:.2f}m): {in_len}")

    def export_preview_csv(self):
        items = [i for i in self.image_data if i.is_inside_threshold]
        if not items: return messagebox.showwarning("Atención", "No hay datos exportables.")
        
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="preview_generado.csv")
        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow(['Original', 'Nuevo Nombre', 'Distancia'])
                    for p in items:
                        w.writerow([p.name, p.new_name_base, p.distance])
                self.log(f"CSV volcado exitosamente.", "success")
            except Exception as e:
                self.log(f"Error IO: {e}", "error")

    def apply_map_filter(self):
        if not self.image_data: return
        map_w = self.tabs.map_widget
        map_w.delete_all_marker()
        map_w.delete_all_path()
        
        filt = getattr(self.tabs, 'map_filter_var', tk.StringVar(value="Todos")).get()
        
        coords = []
        if self.spatial_calc.project_axis:
            coords = [(y, x) for x, y in self.spatial_calc.project_axis.coords]
            if len(coords) > 1:
                map_w.set_path(coords, color="#3498db", width=4)
                
        for pt in self.spatial_calc.named_points:
            map_w.set_marker(pt.lat, pt.lon, text=pt.name, marker_color_circle="#3498db", marker_color_outside="#2980b9")
            
        def make_cb(item):
            def cb(marker):
                st = "🟢 VÁLIDO" if item.is_inside_threshold else "🔴 DESCARTADO"
                self.log(f"📍 INFO FOTO: {item.name} | Sugerido: {item.new_name_base} | {item.distance:.2f}m a PK {item.pk_value} | {st}", "info")
            return cb

        for item in self.image_data:
            if filt == "Válidos" and not item.is_inside_threshold: continue
            if filt == "Descartados" and item.is_inside_threshold: continue
            
            cb = make_cb(item)
            if item.is_inside_threshold:
                map_w.set_marker(item.lat, item.lon, text=item.name, marker_color_circle="#2ecc71", marker_color_outside="#27ae60", command=cb)
            else:
                map_w.set_marker(item.lat, item.lon, text=item.name, marker_color_circle="#e74c3c", marker_color_outside="#c0392b", command=cb)

    def open_map(self):
        if not self.image_data: return
        self.log("Activando mapa interactivo nativo...")
        self.tabs.select(1)
        self.apply_map_filter()
        if self.image_data:
            self.tabs.map_widget.set_position(self.image_data[0].lat, self.image_data[0].lon)
            self.tabs.map_widget.set_zoom(15)
        self.log("Mapa desplegado con capacidades de filtrado.", "success")

    def export_map_pdf(self):
        if not self.image_data: 
            return messagebox.showwarning("Atención", "No hay mapa cargado para exportar.")
            
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", 
            filetypes=[("PDF Document", "*.pdf")],
            initialfile="Acta_Vuelo_Renombrado.pdf"
        )
        
        if not path:
            return
            
        self.log("Generando Snapshot PDF del mapa actual...", "info")
        self.update_idletasks()
        
        # Obtener coordenadas relativas del widget de mapa a la pantalla
        x0 = self.tabs.map_widget.winfo_rootx()
        y0 = self.tabs.map_widget.winfo_rooty()
        x1 = x0 + self.tabs.map_widget.winfo_width()
        y1 = y0 + self.tabs.map_widget.winfo_height()
        
        try:
            # Capturar imagen de la pantalla en esa bounding box
            img = ImageGrab.grab(bbox=(x0, y0, x1, y1))
            
            # Convertir a RGB (necesario para guardado PDF) y guardar
            if img.mode == 'RGBA':
                img = img.convert('RGB')
                
            img.save(path, "PDF", resolution=100.0)
            self.log(f"Acta PDF guardada con éxito en:\n{path}", "success")
            
        except Exception as e:
            self.log(f"Error generando PDF: {e}", "error")

    def confirm_and_process(self):
        items = [i for i in self.image_data if i.is_inside_threshold]
        if not items: return messagebox.showwarning("Atención", "Espectro vacío.")
            
        if not messagebox.askyesno("Confirmar", f"¿Renombrar {len(items)} imágenes?"): return
        
        self.update_ui_state(True)
        self.cancel_requested = False
        self.progress['value'] = 0
        self.tabs.select(1)
        
        fld = self.vars['folder'].get()
        bck = self.vars['backup'].get()
        threading.Thread(target=self._process_task, args=(items, fld, bck), daemon=True).start()

    def confirm_and_restore(self):
        fld = self.vars['folder'].get()
        if not os.path.isdir(fld): 
            return messagebox.showerror("Error", "Carpeta inválida.")
            
        csv_path = os.path.join(fld, "reporte_renombrado.csv")
        if not os.path.exists(csv_path):
            return messagebox.showerror("Aviso", "No existe un archivo reporte_renombrado.csv para revertir en la carpeta actual.")
            
        if not messagebox.askyesno("Confirmar Reversión", "Esto leerá el archivo CSV y devolverá a las fotos sus nombres originales.\n\n¿Estás seguro de que quieres Deshacer los cambios?"):
            return
            
        self.update_ui_state(True)
        self.cancel_requested = False
        threading.Thread(target=self._restore_task, args=(fld,), daemon=True).start()
        
    def _restore_task(self, fld):
        self.log("Iniciando reversión de nombres...", "warning")
        
        def progres_cb(completed: int, total: int, msg: str):
            self.after(0, lambda: self._update_progress(completed, total, msg))
            
        success, msg = self.renamer.undo_last_rename_from_csv(fld, progress_cb=progres_cb)
        
        self.after(0, lambda: self._on_restore_finished(success, msg))
        
    def _on_restore_finished(self, success, msg):
        self.update_ui_state(False)
        self.progress['value'] = 0
        self.stats_lbl.config(text=msg)
        
        if success:
            self.log(msg, "success")
            messagebox.showinfo("Revertido", msg)
            if self.vars['kml'].get() and self.vars['folder'].get():
                self.start_analysis() # Recargar
        else:
            self.log(msg, "error")
            messagebox.showerror("Error", msg)

    def _process_task(self, items, output_folder, backup):
        self.log("Secuencia IO física iniciada.", "info")
        
        def cb(c, t, m):
            self.after(0, lambda: self.progress.configure(value=c, maximum=t))
            if c % 10 == 0 or c == t: self.log(m, "info")
            
        try:
            self.renamer.process_images(items, output_folder, backup, cb, lambda: self.cancel_requested)
            if self.cancel_requested:
                self.log("Corte de hilo inyectado por el usuario.", "warning")
            else:
                self.log("Transacción de IO completada. CSV emitido.", "success")
        except Exception as e:
            self.log(f"Fallo grave en disco: {e}", "error")
            
        self.after(0, lambda: self.update_ui_state(False))

    def cancel_operation(self):
        if self.is_processing:
            self.cancel_requested = True
            self.sidebar.btn_cancel.config(state=DISABLED)
            self.status_lbl.config(text="● Interrumpiendo IO...", foreground="#e74c3c")
            self.log("Injectando señal SIGTERM al procesador...", "warning")

if __name__ == "__main__":
    app = MainWindow()
    app.mainloop()
