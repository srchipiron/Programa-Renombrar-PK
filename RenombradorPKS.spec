# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Renombrador PKS.

Builds a Windows onedir bundle containing the PySide6/Qt UI plus all the
QtWebEngine runtime needed by the embedded map (QtWebEngineProcess.exe,
ICU data, locales, resource .pak files, ...).

Usage:
    pyinstaller --noconfirm RenombradorPKS.spec
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
PROJECT_ROOT = Path(SPECPATH).resolve()

# Windows icon embedded in the .exe and used as the default window icon.
APP_ICON = PROJECT_ROOT / "src" / "assets" / "branding" / "app_icon.ico"
APP_ICON_STR = str(APP_ICON) if APP_ICON.is_file() else None

# ---------------------------------------------------------------------------
# Hidden imports / extra data
# ---------------------------------------------------------------------------
# QtWebEngine ships a bunch of binary assets (ICU data, locales, .pak files)
# and a helper process.  ``collect_all`` pulls everything automatically.
pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
shiboken_datas, shiboken_binaries, shiboken_hidden = collect_all("shiboken6")

# fastkml / pygeoif sometimes have modules loaded lazily.
fastkml_hidden = collect_submodules("fastkml") + collect_submodules("pygeoif")

hiddenimports = [
    "src.ui_qt.app",
    "src.ui_qt.main_window",
    "src.ui_qt.sidebar",
    "src.ui_qt.preview_tab",
    "src.ui_qt.map_tab",
    "src.ui_qt.log_tab",
    "src.ui_qt.help_tab",
    "src.ui_qt.workers",
    "src.ui_qt.theme",
    "src.ui_qt.log_handler",
    "src.ui_qt.histogram",
    "src.ui_qt.undo_history",
    "src.ui_qt.undo_dialog",
    "src.ui_qt.video_dialog",
    "src.core.renamer_logic",
    "src.core.rename_report",
    "src.core.types",
    "src.core.spatial_calculator",
    "src.core.config",
    "src.core.logging_config",
    "src.core.models",
    "src.core.video_extractor",
    "src.map_component",
    *pyside_hidden,
    *shiboken_hidden,
    *fastkml_hidden,
]

binaries = [*pyside_binaries, *shiboken_binaries]
datas = [*pyside_datas, *shiboken_datas]

# Local assets: map HTML template + vendored Leaflet/MarkerCluster so the
# embedded map renders offline even when no CDN is reachable.  ``*_raw.*``
# files are build-time artefacts (e.g. the magenta icon master) and must not
# ship inside the bundle.
assets_dir = PROJECT_ROOT / "src" / "assets"
if assets_dir.is_dir():
    for path in assets_dir.rglob("*"):
        if not path.is_file():
            continue
        if "_raw" in path.stem:
            continue
        rel_parent = path.parent.relative_to(PROJECT_ROOT)
        datas.append((str(path), str(rel_parent)))

# ---------------------------------------------------------------------------
# Analysis / build graph
# ---------------------------------------------------------------------------
a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Legacy Tk UI, never called from main.py.
        "src.ui_legacy",
        "tkinter",
        "ttkbootstrap",
        "tkintermapview",
        # Test-only dependency.
        "pytest",
        "pytest_qt",
        "pytestqt",
        # Heavyweight scientific stack not used at runtime; mostly comes in via
        # shapely's optional paths — we only need the small cython core.
        "scipy",
        "pandas",
        "numpy.distutils",
        "matplotlib",
        "IPython",
        "jupyter",
        "sphinx",
        "setuptools._distutils",
        # Qt modules the app never touches.  QtWebEngine transitively requires
        # QtQml/QtQuick/QtOpenGL/QtPositioning, so we must NOT exclude those.
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DExtras",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DRender",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSerialBus",
        "PySide6.QtRemoteObjects",
        "PySide6.QtHelp",
        "PySide6.QtDesigner",
        "PySide6.QtQuick3D",
        "PySide6.QtTest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# Executable (windowed, no console)
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RenombradorPKS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON_STR,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RenombradorPKS",
)
