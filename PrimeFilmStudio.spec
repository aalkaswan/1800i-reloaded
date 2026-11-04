# -*- mode: python ; coding: utf-8 -*-
# PyInstaller specification file for PrimeFilm 1800u / 1800i Studio
# Builds a standalone single-file Windows executable (PrimeFilmStudio.exe)
# with zero external dependencies (no Python or pip installation required).

import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs

block_cipher = None

datas = []
binaries = []

hidden_imports = [
    'usb.core',
    'usb.backend.libusb1',
    'usb.util',
    'http.server',
    'urllib.parse',
    'json',
    'queue',
    'threading',
    'webbrowser',
    'math',
    'struct',
]

# Collect PySide6 if available
try:
    import PySide6
    hidden_imports += collect_submodules('PySide6')
except ImportError:
    pass

# Collect libusb_package (and its libusb-1.0.dll) if available
try:
    import libusb_package
    hidden_imports += collect_submodules('libusb_package')
    datas += collect_data_files('libusb_package')
    binaries += collect_dynamic_libs('libusb_package')
except (ImportError, Exception):
    pass

a = Analysis(
    ['scripts/primefilm_studio_app.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy.spatial.cKDTree'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PrimeFilmStudio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False, # Avoid upx issues with antivirus false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False, # Set to False for native clean windowed app
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
