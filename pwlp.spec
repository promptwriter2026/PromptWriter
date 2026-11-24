# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

import tkinterdnd2
from PyInstaller.utils.hooks import collect_data_files

PROJECT_DIR = Path(SPECPATH)
TKDND_DIR = Path(tkinterdnd2.__file__).resolve().parent / "tkdnd"

datas = [
    (str(PROJECT_DIR / "promptwriter" / "assets"), "promptwriter/assets"),
    (str(PROJECT_DIR / "defaults"), "defaults"),
    # Whole TkDND tree (native libraries plus Tcl files) keeps drag-and-drop
    # working in the frozen app; tkinterdnd2 loads it relative to its package.
    (str(TKDND_DIR), "tkinterdnd2/tkdnd"),
]
datas += collect_data_files("customtkinter")

# Conda installs keep Tcl/Tk, SQLite, ctypes, and compression runtimes in
# Library/bin, which PyInstaller's dependency scan does not pick up.
RUNTIME_DLLS = (
    "sqlite3.dll",
    "tcl86t.dll",
    "tk86t.dll",
    "ffi.dll",
    "libexpat.dll",
    "libbz2.dll",
    "liblzma.dll",
    "libmpdec-4.dll",
)
BIN_DIRS = [
    Path(sys.base_prefix) / "Library" / "bin",
    Path(sys.base_prefix) / "DLLs",
    Path(sys.base_prefix),
]
binaries = []
for dll_name in RUNTIME_DLLS:
    for folder in BIN_DIRS:
        dll_path = folder / dll_name
        if dll_path.is_file():
            binaries.append((str(dll_path), "."))
            break

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["tkinterdnd2"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "tkinter.test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PWLP",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(PROJECT_DIR / "promptwriter" / "assets" / "promptwriter.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PWLP",
)
