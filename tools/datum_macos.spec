# PyInstaller build for InventCraft on macOS (Apple Silicon and Intel).
#
# Modelled on tools/datum_linux.spec: the OCCT Python module links its
# libraries with @loader_path, which PyInstaller follows the way ldd is
# followed on Linux, so no hand copying of DLL folders is needed the way
# tools/datum.spec does it on Windows.  Run from the repository root:
#
#   .venv/bin/pyinstaller --noconfirm tools/datum_macos.spec
#
# which lays out dist/InventCraft.app.  First launch is from a terminal
# (or `open dist/InventCraft.app`); Finder double-click on an unsigned
# build is stopped by Gatekeeper until the folder is ad-hoc signed:
#
#   codesign --deep --force -s - dist/InventCraft.app

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH).parent

binaries = collect_dynamic_libs("OCP")

datas = [
    (str(ROOT / "datum" / "templates"), "datum/templates"),
    (str(ROOT / "datum" / "ui" / "assets"), "datum/ui/assets"),
    # the beaver, for the window, the Dock and the start page
    (str(ROOT / "datum" / "ui" / "brand"), "datum/ui/brand"),
]

excluded_qt = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DRender",
    "PySide6.QtBluetooth", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtDBus", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtHttpServer", "PySide6.QtLocation", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNetworkAuth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtQuick3D", "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio",
    "PySide6.QtSql", "PySide6.QtStateMachine", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtUiTools", "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtGraphs",
    "PySide6.QtPdfWidgets", "PySide6.QtNetwork",
]

excludes = excluded_qt + [
    "vtkmodules", "vtk",              # the libraries stay, the Python goes
    "matplotlib", "PIL", "pandas", "scipy", "IPython", "jupyter",
    "tkinter", "unittest", "pydoc", "doctest", "pytest",
    "PyInstaller", "setuptools", "pip",
]

a = Analysis(
    [str(ROOT / "datum.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "cryptography.hazmat.primitives.asymmetric.ed25519",
    ],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InventCraft",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="InventCraft",
)

app = BUNDLE(
    coll,
    name="InventCraft.app",
    bundle_identifier="com.iiteg.inventcraft",
)
