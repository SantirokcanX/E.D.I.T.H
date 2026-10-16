# -*- mode: python ; coding: utf-8 -*-
"""EDITH.exe con PyInstaller en modo carpeta (Fase 15.3).

Resultado: dist/EDITH/EDITH.exe (app de ventana, sin consola) + dist/EDITH/_internal/.
No se lanza a mano: lo hace build/build_setup.ps1 con el entorno limpio build/.venv.

  * Punto de entrada: desktop/desktop_app.py (pywebview + bandeja + uvicorn en un hilo).
  * Recursos dentro de _internal/ con la misma estructura que el proyecto (agent/paths.py -> APP_DIR):
    ide/static, desktop/assets y VERSION.
  * Sin UPX: comprimir los .dll da más falsos positivos de antivirus y no ahorra casi nada.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                 VarFileInfo, VarStruct, VSVersionInfo)

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821  (SPECPATH lo define PyInstaller)
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
ICON = ROOT / "desktop" / "assets" / "edith-app.ico"

datas = [
    (str(ROOT / "ide" / "static"), "ide/static"),
    (str(ROOT / "desktop" / "assets"), "desktop/assets"),
    (str(ROOT / "VERSION"), "."),
]
datas += collect_data_files("faster_whisper")  # silero_vad_v6.onnx (filtro de silencio de las notas de voz)

binaries = collect_dynamic_libs("ctranslate2")  # ctranslate2.dll y libiomp5md.dll: no tienen hook propio

hiddenimports = [
    "ide.server",  # uvicorn lo importa por nombre ("ide.server:app"): PyInstaller no lo ve solo
    "pystray._win32",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "self_test",  # desktop/self_test.py (EDITH.exe --self-test)
]
hiddenimports += collect_submodules("uvicorn")

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "desktop_app.py")],
    pathex=[str(ROOT), str(ROOT / "desktop")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "_tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
    optimize=0,  # conserva los assert: la autocomprobación los usa
)
pyz = PYZ(a.pure)  # noqa: F821

numbers = tuple(int(n) for n in VERSION.split(".")[:3]) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable("080A04B0", [
            StringStruct("CompanyName", "EDITH"),
            StringStruct("FileDescription", "EDITH - asistente de IA local"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", "EDITH"),
            StringStruct("OriginalFilename", "EDITH.exe"),
            StringStruct("ProductName", "EDITH"),
            StringStruct("ProductVersion", VERSION),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x080A, 1200])]),
    ],
)

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EDITH",
    icon=str(ICON),
    version=version_info,
    console=False,
    disable_windowed_traceback=False,
    upx=False,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    name="EDITH",
    upx=False,
)
