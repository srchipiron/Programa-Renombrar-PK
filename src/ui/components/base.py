"""
Base UI components and utilities.
"""
import tkinter as tk
import ttkbootstrap as tb
from ttkbootstrap.constants import *
from ttkbootstrap.scrolled import ScrolledFrame
from ttkbootstrap.tooltip import ToolTip
from typing import Optional, Callable, Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class BaseFrame(tb.Frame):
    """Base frame with common functionality."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._setup_ui()
    
    def _setup_ui(self):
        """Override to setup UI components."""
        pass

class CardFrame(BaseFrame):
    """Card-style frame with title and content."""
    
    def __init__(self, master, title: str, **kwargs):
        self.title = title
        super().__init__(master, **kwargs)
        self._build_card()
    
    def _build_card(self):
        """Build card structure."""
        self.configure(borderwidth=1, relief="solid")
        
        # Header
        self.header = tb.Frame(self, padding=5)
        self.header.pack(fill=X)
        
        self.title_label = tb.Label(
            self.header, 
            text=self.title, 
            font=("Segoe UI", 11, "bold")
        )
        self.title_label.pack(side=LEFT)
        
        # Content
        self.content = tb.Frame(self, padding=10)
        self.content.pack(fill=BOTH, expand=YES)

class StatusBar(BaseFrame):
    """Status bar with progress and message display."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.pack(side=BOTTOM, fill=X)
        self._last_message = ""
        self._message_history = []
        self._max_history = 50
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup status bar components."""
        # Status message
        self.status_var = tk.StringVar(value="Listo")
        self.status_label = tb.Label(
            self, 
            textvariable=self.status_var,
            font=("Segoe UI", 9)
        )
        self.status_label.pack(side=LEFT, padx=5)
        
        # Progress bar (hidden by default)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = tb.Progressbar(
            self,
            variable=self.progress_var,
            mode='determinate',
            length=200
        )
        
        # Separator
        tb.Separator(self, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=5)
        
        # Item count
        self.count_var = tk.StringVar(value="0 elementos")
        self.count_label = tb.Label(
            self,
            textvariable=self.count_var,
            font=("Segoe UI", 9)
        )
        self.count_label.pack(side=LEFT, padx=5)
    
    def set_status(self, message: str, timeout: int = None):
        """Update status message with optional auto-clear."""
        self.status_var.set(message)
        self._last_message = message
        self._message_history.append((datetime.now().strftime("%H:%M:%S"), message))
        if len(self._message_history) > self._max_history:
            self._message_history.pop(0)
        logger.debug(f"Status: {message}")
        
        # Auto-clear after timeout if specified
        if timeout:
            self.after(timeout * 1000, lambda: self._clear_if_same(message))
    
    def _clear_if_same(self, message: str):
        """Clear status if it hasn't changed."""
        if self.status_var.get() == message:
            self.status_var.set("Listo")
    
    def show_progress(self, value: float = 0, maximum: float = 100):
        """Show and update progress bar."""
        self.progress_bar.pack(side=RIGHT, padx=5)
        self.progress_bar.configure(maximum=maximum)
        self.progress_var.set(value)
    
    def hide_progress(self):
        """Hide progress bar."""
        self.progress_bar.pack_forget()
    
    def set_count(self, count: int, total: int = None):
        """Update item count display."""
        if total:
            self.count_var.set(f"{count}/{total} elementos")
        else:
            self.count_var.set(f"{count} elementos")

class ActionButton(tb.Button):
    """Enhanced button with loading state."""
    
    def __init__(self, master, **kwargs):
        self.original_text = kwargs.get('text', '')
        self.original_command = kwargs.get('command', None)
        self.is_loading = False
        
        super().__init__(master, **kwargs)
        self._setup_state()
    
    def _setup_state(self):
        """Setup initial state."""
        self.configure(state=NORMAL)
    
    def set_loading(self, loading: bool, text: str = None):
        """Set loading state."""
        self.is_loading = loading
        
        if loading:
            self.configure(state=DISABLED)
            if text:
                self.configure(text=text)
            else:
                self.configure(text=f"{self.original_text}...")
        else:
            self.configure(state=NORMAL)
            self.configure(text=self.original_text)

class LabeledEntry(BaseFrame):
    """Entry widget with label."""
    
    def __init__(self, master, label_text: str, **kwargs):
        self.label_text = label_text
        self.var = kwargs.pop('textvariable', tk.StringVar())
        super().__init__(master, **kwargs)
        self._build_widget()
    
    def _build_widget(self):
        """Build labeled entry."""
        self.pack(fill=X, pady=2)
        
        # Label
        self.label = tb.Label(self, text=self.label_text)
        self.label.pack(anchor=W)
        
        # Entry frame
        entry_frame = tb.Frame(self)
        entry_frame.pack(fill=X, pady=(2, 5))
        
        # Entry
        self.entry = tb.Entry(entry_frame, textvariable=self.var)
        self.entry.pack(side=LEFT, fill=X, expand=YES)
        
        # Optional button slot
        self.button_frame = tb.Frame(entry_frame)
        self.button_frame.pack(side=RIGHT, padx=(5, 0))
    
    def add_button(self, text: str, command: Callable, **kwargs):
        """Add button to the entry."""
        btn = tb.Button(
            self.button_frame,
            text=text,
            command=command,
            **kwargs
        )
        btn.pack(side=LEFT, padx=(2, 0))
        return btn
    
    def get(self) -> str:
        """Get entry value."""
        return self.var.get()
    
    def set(self, value: str):
        """Set entry value."""
        self.var.set(value)

class FileSelector(LabeledEntry):
    """File/folder selector with browse button and validation."""
    
    def __init__(self, master, label_text: str, file_mode: str = 'folder', 
                 tooltip_text: str = None, validate_exists: bool = True, **kwargs):
        self.file_mode = file_mode  # 'folder' or 'file'
        self.file_types = kwargs.pop('file_types', [('All files', '*.*')])
        self.validate_exists = validate_exists
        super().__init__(master, label_text, **kwargs)
        self._add_browse_button()
        
        # Add tooltip if provided
        if tooltip_text:
            ToolTip(self.entry, text=tooltip_text, bootstyle=(INFO, INVERSE))
        
        # Add validation
        self.var.trace_add('write', self._on_path_changed)
        self._is_valid = False
    
    def _add_browse_button(self):
        """Add browse button."""
        if self.file_mode == 'folder':
            btn_text = "📁 Examinar"
            command = self._browse_folder
        else:
            btn_text = "📄 Examinar"
            command = self._browse_file
        
        self.browse_btn = self.add_button(btn_text, command, bootstyle=SECONDARY)
        ToolTip(self.browse_btn, text="Haz clic para buscar", bootstyle=(INFO, INVERSE))
    
    def _on_path_changed(self, *args):
        """Validate path when it changes."""
        path = self.get()
        if not path:
            self._is_valid = False
            self.entry.configure(bootstyle=DEFAULT)
            return
        
        if self.validate_exists:
            exists = os.path.exists(path)
            self._is_valid = exists
            # Visual feedback
            if exists:
                self.entry.configure(bootstyle=SUCCESS)
            else:
                self.entry.configure(bootstyle=DANGER)
        else:
            self._is_valid = True
            self.entry.configure(bootstyle=DEFAULT)
    
    def is_valid(self) -> bool:
        """Check if current path is valid."""
        return self._is_valid
    
    def _browse_folder(self):
        """Browse for folder."""
        from tkinter import filedialog
        initial_dir = self.get() if os.path.exists(self.get()) else None
        folder = filedialog.askdirectory(initialdir=initial_dir)
        if folder:
            self.set(folder)
    
    def _browse_file(self):
        """Browse for file."""
        from tkinter import filedialog
        initial_dir = os.path.dirname(self.get()) if os.path.exists(self.get()) else None
        file = filedialog.askopenfilename(
            initialdir=initial_dir,
            filetypes=self.file_types
        )
        if file:
            self.set(file)

class ToolBar(BaseFrame):
    """Toolbar with common actions."""
    
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.pack(side=TOP, fill=X, padx=5, pady=5)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup toolbar."""
        self.configure(padding=5)
    
    def add_button(self, text: str, command: Callable, **kwargs) -> tb.Button:
        """Add button to toolbar."""
        btn = tb.Button(self, text=text, command=command, **kwargs)
        btn.pack(side=LEFT, padx=2)
        return btn
    
    def add_separator(self):
        """Add separator to toolbar."""
        tb.Separator(self, orient=VERTICAL).pack(side=LEFT, fill=Y, padx=5)

class MessageBox:
    """Utility class for showing message boxes."""
    
    @staticmethod
    def show_info(title: str, message: str, parent=None):
        """Show info message."""
        tb.Messagebox.show_info(message, title, parent=parent)
    
    @staticmethod
    def show_warning(title: str, message: str, parent=None):
        """Show warning message."""
        tb.Messagebox.show_warning(message, title, parent=parent)
    
    @staticmethod
    def show_error(title: str, message: str, parent=None):
        """Show error message."""
        tb.Messagebox.show_error(message, title, parent=parent)
    
    @staticmethod
    def ask_yesno(title: str, message: str, parent=None) -> bool:
        """Ask yes/no question."""
        return tb.Messagebox.yesno(message, title, parent=parent)
    
    @staticmethod
    def ask_okcancel(title: str, message: str, parent=None) -> bool:
        """Ask ok/cancel question."""
        return tb.Messagebox.okcancel(message, title, parent=parent)
