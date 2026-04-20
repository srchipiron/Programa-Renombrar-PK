import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import datetime
import tkintermapview

class TabsPanel(tb.Notebook):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.pack(side=LEFT, fill=BOTH, expand=YES, padx=(10,0))
        
        self.tree = None
        self.log_txt = None
        self.map_widget = None
        
        self._build_preview_tab()
        self._build_map_tab()
        self._build_log_tab()
        self._build_help_tab()
        
    def _build_preview_tab(self):
        f = tb.Frame(self, padding=10)
        self.add(f, text="📋 Vista Previa")
        
        columns = ("original", "nuevo", "pk", "distancia")
        self.tree = tb.Treeview(f, columns=columns, show="headings", bootstyle=INFO)
        self.tree.heading("original", text="Archivo Original")
        self.tree.heading("nuevo", text="Nuevo Nombre Sugerido")
        self.tree.heading("pk", text="Punto PK")
        self.tree.heading("distancia", text="Distancia (m)")
        
        self.tree.column("original", width=250)
        self.tree.column("nuevo", width=250)
        self.tree.column("pk", width=150, anchor=CENTER)
        self.tree.column("distancia", width=100, anchor=E)
        
        scrollbar = tb.Scrollbar(f, orient=VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

    def _build_map_tab(self):
        f = tb.Frame(self)
        self.add(f, text="🗺️ Mapa Interactivo")
        
        ctrl_f = tb.Frame(f, padding=5)
        ctrl_f.pack(fill=X)
        
        self.map_filter_var = tk.StringVar(value="Todos")
        tb.Label(ctrl_f, text="Filtro:", font=("Segoe UI", 10, "bold")).pack(side=LEFT, padx=(0, 10))
        
        tb.Radiobutton(ctrl_f, text="Todos", variable=self.map_filter_var, value="Todos", bootstyle=INFO).pack(side=LEFT, padx=5)
        tb.Radiobutton(ctrl_f, text="Sólo Válidos", variable=self.map_filter_var, value="Válidos", bootstyle=SUCCESS).pack(side=LEFT, padx=5)
        tb.Radiobutton(ctrl_f, text="Sólo Descartados", variable=self.map_filter_var, value="Descartados", bootstyle=DANGER).pack(side=LEFT, padx=5)
        
        # Botón extra: PDF Snapshot
        self.btn_snapshot = tb.Button(ctrl_f, text="📸 Exportar Vista (PDF)", bootstyle=WARNING)
        self.btn_snapshot.pack(side=LEFT, padx=20)
        
        tb.Label(ctrl_f, text="🔴 Exced", font=("Segoe UI", 9, "bold"), foreground="#e74c3c").pack(side=RIGHT, padx=5)
        tb.Label(ctrl_f, text="🟢 OK", font=("Segoe UI", 9, "bold"), foreground="#2ecc71").pack(side=RIGHT, padx=5)
        tb.Label(ctrl_f, text="🔵 PK", font=("Segoe UI", 9, "bold"), foreground="#3498db").pack(side=RIGHT, padx=5)
        
        # Selector de capa base
        self.map_layer_var = tk.StringVar(value="Google Satélite (Alta Res)")
        layers = [
            "Google Satélite (Alta Res)", 
            "Esri Satélite (World Imagery)",
            "Google Maps (Terreno/Relieve)",
            "Google Maps (Normal)",
            "OpenStreetMap"
        ]
        combo = tb.Combobox(ctrl_f, textvariable=self.map_layer_var, values=layers, state="readonly", width=28)
        combo.pack(side=RIGHT, padx=10)
        tb.Label(ctrl_f, text="Capa Base:", font=("Segoe UI", 9)).pack(side=RIGHT)
        
        self.map_widget = tkintermapview.TkinterMapView(f, corner_radius=0)
        self.map_widget.pack(fill=BOTH, expand=YES)
        self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        
        combo.bind("<<ComboboxSelected>>", self._change_map_layer)

    def _change_map_layer(self, event=None):
        layer = self.map_layer_var.get()
        if layer == "Google Satélite (Alta Res)":
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=s&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        elif layer == "Esri Satélite (World Imagery)":
            self.map_widget.set_tile_server("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", max_zoom=19)
        elif layer == "Google Maps (Terreno/Relieve)":
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=p&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        elif layer == "Google Maps (Normal)":
            self.map_widget.set_tile_server("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}&s=Ga", max_zoom=22)
        elif layer == "OpenStreetMap":
            self.map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png", max_zoom=19)

    def _build_log_tab(self):
        f = tb.Frame(self, padding=10)
        self.add(f, text="📝 Log")
        
        bg_color = "#1a1d21"
        self.log_txt = tk.Text(f, bg=bg_color, fg="#ffffff", font=("Consolas", 10), state=DISABLED)
        self.log_txt.tag_config("info", foreground="#17a2b8")
        self.log_txt.tag_config("success", foreground="#2ecc71")
        self.log_txt.tag_config("warning", foreground="#f39c12")
        self.log_txt.tag_config("error", foreground="#e74c3c")
        
        scrollbar = tb.Scrollbar(f, orient=VERTICAL, command=self.log_txt.yview)
        self.log_txt.configure(yscrollcommand=scrollbar.set)
        
        self.log_txt.pack(side=LEFT, fill=BOTH, expand=YES)
        scrollbar.pack(side=RIGHT, fill=Y)

    def _build_help_tab(self):
        f = tb.Frame(self, padding=20)
        self.add(f, text="❓ Ayuda")
        help_text = """
Renombrador PKS Febrero 2026 - Instrucciones:

1. Seleccione la carpeta origen de sus fotos (.jpg, .png).
2. Seleccione el archivo de referencia (KML o KMZ).
3. Haga clic en "Analizar Datos":
   - El sistema calculará la distancia desde cada coordenada GPS al P.K. más cercano de la traza KML.
4. Ajuste el sufijo (p.ej 'DIC25') para integrarlo en su nomenclatura final.
5. Indique un umbral de distancia máximo o haga clic en "Auto" para que la Inteligencia K-Means lo destile.
6. Revise en "Vista Previa" los valores en color verde (Renombrables).
7. Puede exportar el Preview a CSV y abrir el HTML Interactivo "Abrir Mapa HTML".
8. Proceda con "Procesar Imágenes". (Crea backup seguro opcional).
        """
        tb.Label(f, text=help_text.strip(), justify=LEFT, font=("Segoe UI", 11)).pack(anchor=NW)

    def insert_log(self, msg: str, level: str = "info"):
        self.log_txt.config(state=NORMAL)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_txt.insert(END, f"[{timestamp}] {msg}\n", level)
        self.log_txt.see(END)
        self.log_txt.config(state=DISABLED)
        
    def clear_preview(self):
        self.tree.delete(*self.tree.get_children())
        
    def insert_preview_row(self, original: str, nuevo: str, pk: str, dist: float):
        self.tree.insert("", END, values=(original, nuevo, pk, f"{dist:.2f}"))
