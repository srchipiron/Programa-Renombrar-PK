"""Theme management for the Qt UI.

Provides two curated QSS stylesheets (dark and light) and small helpers so the
rest of the UI can forget about colors and focus on behavior.
"""
from __future__ import annotations

from typing import Literal

ThemeName = Literal["dark", "light", "system"]


def _detect_system_theme() -> ThemeName:
    """Best-effort detection of the OS dark/light preference.

    On Windows we read the ``AppsUseLightTheme`` registry value; on any
    failure we default to dark so the UI still looks consistent.
    """
    try:
        import sys
        if sys.platform != "win32":
            return "dark"
        import winreg  # type: ignore[import-not-found]
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        finally:
            winreg.CloseKey(key)
        return "light" if value else "dark"
    except Exception:
        return "dark"


_DARK_QSS = """
* {
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 10pt;
    color: #e6edf3;
}

QMainWindow, QWidget {
    background-color: #0f172a;
}

QToolTip {
    color: #e6edf3;
    background-color: #1e293b;
    border: 1px solid #334155;
    padding: 6px 8px;
    border-radius: 6px;
}

QMenuBar {
    background-color: #0b1220;
    color: #e6edf3;
    padding: 4px 6px;
    border-bottom: 1px solid #1e293b;
}
QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: #1e293b; }

QMenu {
    background: #111827;
    border: 1px solid #1e293b;
    padding: 6px;
    border-radius: 8px;
}
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #1e293b; color: #ffffff; }

QDockWidget {
    color: #e6edf3;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}
QDockWidget::title {
    text-align: left;
    background: #0b1220;
    padding: 8px 12px;
    border-bottom: 1px solid #1e293b;
    font-weight: 600;
}

QTabWidget::pane {
    border: 1px solid #1e293b;
    background: #0b1220;
    border-radius: 10px;
}
QTabBar::tab {
    background: #0f172a;
    color: #94a3b8;
    padding: 8px 16px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1e293b;
    color: #ffffff;
}

QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background: #111827;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}
QLineEdit[state="ok"]   { border: 1px solid #10b981; }
QLineEdit[state="bad"]  { border: 1px solid #ef4444; }

QPushButton {
    background: #1e293b;
    border: 1px solid #334155;
    color: #e6edf3;
    padding: 8px 14px;
    border-radius: 8px;
    font-weight: 500;
}
QPushButton:hover   { background: #273449; }
QPushButton:pressed { background: #1e293b; }
QPushButton:disabled { background: #111827; color: #64748b; border-color: #1e293b; }

QPushButton[variant="primary"] {
    background: #3b82f6; border-color: #3b82f6; color: #ffffff;
}
QPushButton[variant="primary"]:hover  { background: #2563eb; border-color: #2563eb; }
QPushButton[variant="success"] {
    background: #10b981; border-color: #10b981; color: #072016;
}
QPushButton[variant="success"]:hover  { background: #059669; border-color: #059669; color: #ffffff; }
QPushButton[variant="danger"] {
    background: #ef4444; border-color: #ef4444; color: #ffffff;
}
QPushButton[variant="danger"]:hover   { background: #dc2626; border-color: #dc2626; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #334155;
    border-radius: 4px;
    background: #111827;
}
QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; }

QProgressBar {
    border: 1px solid #1e293b;
    border-radius: 6px;
    background: #0b1220;
    text-align: center;
    color: #e6edf3;
    height: 14px;
}
QProgressBar::chunk {
    background: #3b82f6;
    border-radius: 6px;
}

QStatusBar { background: #0b1220; border-top: 1px solid #1e293b; }
QStatusBar::item { border: none; }

QHeaderView::section {
    background: #0b1220; color: #94a3b8; padding: 6px 10px;
    border: none; border-bottom: 1px solid #1e293b;
}
QTableView {
    background: #0b1220; alternate-background-color: #0f172a;
    gridline-color: #1e293b; selection-background-color: #1d4ed8;
    selection-color: #ffffff; border: 1px solid #1e293b; border-radius: 8px;
}
QTableView::item { padding: 4px 6px; }

QScrollBar:vertical   { background: transparent; width: 10px; margin: 4px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 4px; }
QScrollBar::handle    { background: #334155; border-radius: 4px; min-height: 20px; }
QScrollBar::handle:hover { background: #475569; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; height: 0; width: 0; }

QLabel[role="section"] {
    font-weight: 600;
    color: #94a3b8;
    letter-spacing: 0.4px;
    padding-top: 2px;
}
QLabel[role="muted"] { color: #94a3b8; }
QFrame[role="hline"] { color: #1e293b; max-height: 1px; }
QLabel#workflowBanner {
    background: #111827;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px 12px;
    color: #cbd5e1;
    line-height: 1.35;
}
QLabel#workflowBanner[level="success"] {
    border-color: #10b981;
    background: #052e1f;
    color: #d1fae5;
}
QLabel#workflowBanner[level="warning"] {
    border-color: #f59e0b;
    background: #422006;
    color: #fde68a;
}
QLabel#previewEmpty {
    background: #0b1220;
    border: 1px dashed #334155;
    border-radius: 12px;
    color: #94a3b8;
    padding: 32px 24px;
    font-size: 11pt;
}
QFrame#thumbFrame {
    background: #0b1220;
    border: 1px solid #1e293b;
    border-radius: 8px;
}
"""


_LIGHT_QSS = """
* {
    font-family: "Segoe UI", "Inter", "Roboto", sans-serif;
    font-size: 10pt;
    color: #0f172a;
}

QMainWindow, QWidget { background-color: #f8fafc; }

QToolTip {
    color: #0f172a; background-color: #ffffff;
    border: 1px solid #cbd5e1; padding: 6px 8px; border-radius: 6px;
}

QMenuBar { background-color: #ffffff; color: #0f172a; padding: 4px 6px; border-bottom: 1px solid #e2e8f0; }
QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 6px; }
QMenuBar::item:selected { background: #e2e8f0; }

QMenu { background: #ffffff; border: 1px solid #e2e8f0; padding: 6px; border-radius: 8px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #e2e8f0; color: #0f172a; }

QDockWidget::title {
    text-align: left; background: #ffffff;
    padding: 8px 12px; border-bottom: 1px solid #e2e8f0; font-weight: 600;
}

QTabWidget::pane { border: 1px solid #e2e8f0; background: #ffffff; border-radius: 10px; }
QTabBar::tab {
    background: #e2e8f0; color: #334155; padding: 8px 16px;
    border-top-left-radius: 8px; border-top-right-radius: 8px; margin-right: 2px;
}
QTabBar::tab:selected { background: #ffffff; color: #0f172a; }

QLineEdit, QPlainTextEdit, QTextEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background: #ffffff; border: 1px solid #cbd5e1; border-radius: 8px;
    padding: 6px 10px; selection-background-color: #3b82f6; selection-color: #ffffff;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #3b82f6; }
QLineEdit[state="ok"]  { border: 1px solid #10b981; }
QLineEdit[state="bad"] { border: 1px solid #ef4444; }

QPushButton {
    background: #ffffff; border: 1px solid #cbd5e1; color: #0f172a;
    padding: 8px 14px; border-radius: 8px; font-weight: 500;
}
QPushButton:hover { background: #f1f5f9; }
QPushButton:pressed { background: #e2e8f0; }
QPushButton:disabled { color: #94a3b8; background: #f1f5f9; border-color: #e2e8f0; }

QPushButton[variant="primary"] { background: #3b82f6; border-color: #3b82f6; color: #ffffff; }
QPushButton[variant="primary"]:hover  { background: #2563eb; border-color: #2563eb; }
QPushButton[variant="success"] { background: #10b981; border-color: #10b981; color: #ffffff; }
QPushButton[variant="success"]:hover  { background: #059669; border-color: #059669; }
QPushButton[variant="danger"] { background: #ef4444; border-color: #ef4444; color: #ffffff; }
QPushButton[variant="danger"]:hover   { background: #dc2626; border-color: #dc2626; }

QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #cbd5e1;
    border-radius: 4px; background: #ffffff;
}
QCheckBox::indicator:checked { background: #3b82f6; border-color: #3b82f6; }

QProgressBar {
    border: 1px solid #e2e8f0; border-radius: 6px; background: #ffffff;
    text-align: center; color: #0f172a; height: 14px;
}
QProgressBar::chunk { background: #3b82f6; border-radius: 6px; }

QStatusBar { background: #ffffff; border-top: 1px solid #e2e8f0; }

QHeaderView::section {
    background: #ffffff; color: #475569; padding: 6px 10px;
    border: none; border-bottom: 1px solid #e2e8f0;
}
QTableView {
    background: #ffffff; alternate-background-color: #f8fafc;
    gridline-color: #e2e8f0; selection-background-color: #3b82f6;
    selection-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px;
}
QTableView::item { padding: 4px 6px; }

QScrollBar:vertical   { background: transparent; width: 10px; margin: 4px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 4px; }
QScrollBar::handle    { background: #cbd5e1; border-radius: 4px; min-height: 20px; }
QScrollBar::handle:hover { background: #94a3b8; }
QScrollBar::add-line, QScrollBar::sub-line { background: none; border: none; height: 0; width: 0; }

QLabel[role="section"] {
    font-weight: 600;
    color: #64748b;
    letter-spacing: 0.4px;
    padding-top: 2px;
}
QLabel[role="muted"] { color: #64748b; }
QFrame[role="hline"] { color: #e2e8f0; max-height: 1px; }
QLabel#workflowBanner {
    background: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 10px 12px;
    color: #334155;
    line-height: 1.35;
}
QLabel#workflowBanner[level="success"] {
    border-color: #10b981;
    background: #ecfdf5;
    color: #065f46;
}
QLabel#workflowBanner[level="warning"] {
    border-color: #f59e0b;
    background: #fffbeb;
    color: #92400e;
}
QLabel#previewEmpty {
    background: #f8fafc;
    border: 1px dashed #cbd5e1;
    border-radius: 12px;
    color: #64748b;
    padding: 32px 24px;
    font-size: 11pt;
}
QFrame#thumbFrame {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
}
"""


def resolve(theme: ThemeName) -> ThemeName:
    """Return the concrete ``dark``/``light`` name, resolving ``system``."""
    if theme == "system":
        return _detect_system_theme()
    return theme if theme in ("dark", "light") else "dark"


def get_stylesheet(theme: ThemeName) -> str:
    concrete = resolve(theme)
    return _DARK_QSS if concrete == "dark" else _LIGHT_QSS


def toggle(theme: ThemeName) -> ThemeName:
    """Cycle dark → light → system → dark …"""
    if theme == "dark":
        return "light"
    if theme == "light":
        return "system"
    return "dark"
