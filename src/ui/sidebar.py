import os
import tkinter as tk
from tkinter import filedialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.tooltip import ToolTip
from typing import Callable

class SidebarPanel(ScrolledFrame):
    def __init__(self, master, callbacks: dict, state_vars: dict, **kwargs):
        super().__init__(master, **kwargs)
        self.pack(side=LEFT, fill=Y, padx=(0,0), pady=(0,0))
        
        self.callbacks = callbacks
        self.vars = state_vars
        
        # References to buttons that might be disabled
        self.btn_analyze = None
        self.btn_auto_threshold = None
        self.btn_preview = None
        self.btn_export_csv = None
        self.btn_process = None
        self.btn_cancel = None
        self.btn_map = None
        self.entry_threshold = None
        
        self._build_files_card()
        self._build_config_card()
        self._build_actions_card()
        self._build_map_card()
        
    def _create_card(self, title: str) -> tb.Frame:
        card = tb.Frame(self, borderwidth=1, relief="solid")
        card.pack(fill=X, pady=5, padx=5)
        hf = tb.Frame(card, padding=5)
        hf.pack(fill=X)
        tb.Label(hf, text=title, font=("Segoe UI", 11, "bold")).pack(side=LEFT)
        content = tb.Frame(card, padding=10)
        content.pack(fill=BOTH, expand=YES)
        return content

    def _build_files_card(self):
        card = self._create_card("📁 Archivos")
        
        tb.Label(card, text="Carpeta de Imágenes:").pack(anchor=W)
        f_frame = tb.Frame(card)
        f_frame.pack(fill=X, pady=(0, 10))
        tb.Entry(f_frame, textvariable=self.vars['folder'], state='readonly').pack(side=LEFT, fill=X, expand=YES, padx=(0,5))
        tb.Button(f_frame, text="Abrir", command=self.callbacks['open_folder'], bootstyle=INFO).pack(side=RIGHT, padx=(5,0))
        tb.Button(f_frame, text="Examinar", command=self.callbacks['select_folder'], bootstyle=SECONDARY).pack(side=RIGHT)
        
        tb.Label(card, text="Archivo KML/KMZ:").pack(anchor=W)
        k_frame = tb.Frame(card)
        k_frame.pack(fill=X, pady=(0, 15))
        tb.Entry(k_frame, textvariable=self.vars['kml'], state='readonly').pack(side=LEFT, fill=X, expand=YES, padx=(0,5))
        tb.Button(k_frame, text="Examinar", command=self.callbacks['select_kml'], bootstyle=SECONDARY).pack(side=RIGHT)
        
        self.btn_srt = tb.Button(card, text="🎬 Cargar Vídeo SRT", command=self.callbacks.get('select_srt', lambda: None), bootstyle="info-outline")
        self.btn_srt.pack(fill=X, pady=(0, 10))
        
        self.btn_analyze = tb.Button(card, text="🔍 Analizar Datos", command=self.callbacks['analyze'], bootstyle="primary-outline")
        self.btn_analyze.pack(fill=X)

    def _build_config_card(self):
        card = self._create_card("⚙️ Configuración")
        
        tb.Label(card, text="Plantilla Nombre (tags: [PK], [FECHA], [HORA], [ORIG]):").pack(anchor=W)
        t_entry = tb.Entry(card, textvariable=self.vars['suffix'])
        t_entry.pack(fill=X, pady=(0, 10))
        ToolTip(t_entry, text="Deje en blanco para usar solo el PK.\nUse etiquetas como: [PK]-[ORIG], [PK]_[FECHA]-[HORA]_Obras, etc.")
        
        tb.Label(card, text="Umbral máx distancia (metros):").pack(anchor=W)
        t_frame = tb.Frame(card)
        t_frame.pack(fill=X, pady=(0, 10))
        self.entry_threshold = tb.Entry(t_frame, textvariable=self.vars['threshold'])
        self.entry_threshold.pack(side=LEFT, fill=X, expand=YES, padx=(0, 5))
        self.btn_auto_threshold = tb.Button(t_frame, text="Auto", bootstyle=INFO, command=self.callbacks['auto_threshold'], state=DISABLED)
        self.btn_auto_threshold.pack(side=RIGHT)
        ToolTip(self.btn_auto_threshold, text="Calcula el umbral óptimo automáticamente usando agrupación K-Means\nsegún la distribución de distancias detectadas.")
        
        tb.Checkbutton(card, text="Crear Backup (_backup_originales)", variable=self.vars['backup'], bootstyle="round-toggle").pack(anchor=W, pady=5)

    def _build_actions_card(self):
        card = self._create_card("⚡ Acciones")
        
        self.btn_preview = tb.Button(card, text="👁️ Vista Previa", command=self.callbacks['preview'], bootstyle=INFO, state=DISABLED)
        self.btn_preview.pack(fill=X, pady=5)
        
        self.btn_export_csv = tb.Button(card, text="💾 Exportar Preview", command=self.callbacks['export_csv'], bootstyle=SECONDARY, state=DISABLED)
        self.btn_export_csv.pack(fill=X, pady=5)
        
        self.btn_process = tb.Button(card, text="▶️ Procesar Imágenes", command=self.callbacks['process'], bootstyle=SUCCESS, state=DISABLED)
        self.btn_process.pack(fill=X, pady=5)
        
        self.btn_undo = tb.Button(card, text="⏪ Deshacer (CSV)", command=self.callbacks.get('undo', lambda: None), bootstyle=WARNING)
        self.btn_undo.pack(fill=X, pady=5)
        
        self.btn_cancel = tb.Button(card, text="⏹️ Cancelar", command=self.callbacks['cancel'], bootstyle=DANGER)

    def _build_map_card(self):
        card = self._create_card("🗺️ Mapa")
        self.btn_map = tb.Button(card, text="🌍 Ver Mapa en Pestaña", command=self.callbacks['open_map'], bootstyle=WARNING, state=DISABLED)
        self.btn_map.pack(fill=X)
        
    def set_state(self, is_processing: bool, has_data: bool):
        state = DISABLED if is_processing else NORMAL
        self.btn_analyze.config(state=state)
        self.entry_threshold.config(state=state)
        
        if is_processing:
            self.btn_cancel.pack(fill=X, pady=5)
            self.btn_preview.config(state=DISABLED)
            self.btn_process.config(state=DISABLED)
            self.btn_map.config(state=DISABLED)
            self.btn_export_csv.config(state=DISABLED)
            self.btn_auto_threshold.config(state=DISABLED)
        else:
            self.btn_cancel.pack_forget()
            if has_data:
                self.btn_preview.config(state=NORMAL)
                self.btn_process.config(state=NORMAL)
                self.btn_map.config(state=NORMAL)
                self.btn_export_csv.config(state=NORMAL)
                self.btn_auto_threshold.config(state=NORMAL)
