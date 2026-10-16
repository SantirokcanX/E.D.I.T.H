"""Pruebas de la Fase 15.3 (empaquetado): versión única, modo congelado, bridge empaquetado y
autocomprobación. El ejecutable de verdad (dist/EDITH/EDITH.exe) se prueba con
build/build_setup.ps1 y arrancándolo con --tray (ver "Registro de Cambios de EDITH", v0.0.9).
Uso:  python tests/test_fase_15_3.py   (desde la raíz del proyecto, con el .venv activado)
"""
import os
import re
import shutil
import sys

os.environ["ML_ENABLED"] = "false"
from entorno import ROOT, TMP, check, summary  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
import agent.paths as paths  # noqa: E402
import ide.channels_api as channels_api  # noqa: E402
import ide.server as srv  # noqa: E402
from agent.channels.security import get_api_token  # noqa: E402

BEARER = {"Authorization": f"Bearer {get_api_token()}"}
client = TestClient(srv.app, base_url="http://127.0.0.1:8000")

# ======================= 1. versión única =======================
file_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
check("VERSION con formato x.y.z", re.fullmatch(r"\d+\.\d+\.\d+", file_version), file_version)
check("la app lee el archivo VERSION", paths.VERSION == file_version, paths.VERSION)
r = client.get("/api/version", headers=BEARER)
check("/api/version (desde el código: packaged=false)",
      r.status_code == 200 and r.json() == {"version": file_version, "packaged": False}, r.text)
check("/api/version pide token como el resto de la API", client.get("/api/version").status_code == 401)
page = client.get("/", headers=BEARER).text
check("la interfaz enlaza CSS y JS con la versión", all(f"{name}?v={file_version}" in page
                                                        for name in ("styles.css", "render.js", "setup.js", "app.js")))
check("no queda ningún {{EDITH_VERSION}} sin sustituir", "{{EDITH_VERSION}}" not in page)
check("/index.html sirve lo mismo", client.get("/index.html", headers=BEARER).text == page)
bat =(ROOT / "desktop" / "launcher" / "build_launcher.bat").read_text(encoding="utf-8")
cs = (ROOT / "desktop" / "launcher" / "EDITH.cs").read_text(encoding="utf-8")
check("el lanzador toma la versión del archivo VERSION (sin versión fija en EDITH.cs)",
      "VERSION" in bat and "AssemblyVersion(\"" not in cs)
spec = (ROOT / "build" / "edith.spec").read_text(encoding="utf-8")
check("la spec de PyInstaller lee VERSION y empaqueta interfaz, iconos y VERSION",
      '"VERSION"' in spec and '"ide/static"' in spec and '"desktop/assets"' in spec and "console=False" in spec)

# ======================= 2. modo congelado (EDITH.exe) =======================
proj = TMP / "proyecto"
proj.mkdir()
(proj / ".env").write_text("EDITH_VOICE=ximena\n", encoding="utf-8")
home = TMP / "home_frozen"
home.mkdir()
saved = (paths.FROZEN, paths.PROJECT_DIR, paths.EDITH_HOME)
try:
    paths.PROJECT_DIR, paths.EDITH_HOME = proj, home
    paths.FROZEN = False
    check("desde el código se usa el .env del proyecto", paths.env_file() == proj / ".env")
    paths.FROZEN = True
    check("en la app empaquetada siempre el .env de EDITH_HOME", paths.env_file() == home / ".env")
finally:
    paths.FROZEN, paths.PROJECT_DIR, paths.EDITH_HOME = saved

marker = home / ".migrado_desde_proyecto"
check("sin marca de migración no se copia ningún .env", paths.adopt_project_env(home / ".env", marker) is None)
marker.write_text(f"Datos copiados desde {proj} el 2026-10-16 10:00 (3 archivos).\nLas carpetas data/ ...\n",
                  encoding="utf-8")
copied = paths.adopt_project_env(home / ".env", marker)
check("la app empaquetada adopta el .env del proyecto de la marca (una vez)",
      copied == proj / ".env" and (home / ".env").read_text(encoding="utf-8") == "EDITH_VOICE=ximena\n", copied)
(home / ".env").write_text("EDITH_VOICE=dalia\n", encoding="utf-8")
check("... y nunca pisa un .env que ya existe", paths.adopt_project_env(home / ".env", marker) is None
      and "dalia" in (home / ".env").read_text(encoding="utf-8"))
marker.write_text(f"Datos copiados desde {TMP / 'no_existe'} el 2026-10-16 10:00 (0 archivos).\n", encoding="utf-8")
(home / ".env").unlink()
check("si el proyecto de la marca ya no existe, no pasa nada", paths.adopt_project_env(home / ".env", marker) is None)

# ======================= 3. bridge de WhatsApp empaquetado =======================
fake_exe = TMP / "dist" / "edith-whatsapp.exe"
fake_exe.parent.mkdir()
saved = (channels_api.FROZEN, channels_api.BRIDGE_EXE, channels_api.shutil.which)
try:
    channels_api.BRIDGE_EXE = fake_exe
    channels_api.FROZEN = False
    channels_api.shutil.which = lambda name: None
    check("sin Node ni edith-whatsapp.exe no hay bridge", channels_api.bridge_command() is None)
    fake_exe.write_bytes(b"MZ")
    cmd = channels_api.bridge_command()
    check("sin Node pero con edith-whatsapp.exe: usa el .exe", cmd == ([str(fake_exe)], fake_exe.parent), cmd)
    channels_api.shutil.which = lambda name: r"C:\Program Files\nodejs\node.exe"
    modules = (channels_api.BRIDGE_DIR / "node_modules").exists()
    cmd = channels_api.bridge_command()
    check("desde el código con Node: bridge.mjs (cambios al momento)",
          cmd == ([r"C:\Program Files\nodejs\node.exe", "bridge.mjs"], channels_api.BRIDGE_DIR) if modules
          else cmd[0] == [str(fake_exe)], cmd)
    channels_api.FROZEN = True
    cmd = channels_api.bridge_command()
    check("en la app empaquetada nunca exige Node: siempre el .exe", cmd == ([str(fake_exe)], fake_exe.parent), cmd)
finally:
    channels_api.FROZEN, channels_api.BRIDGE_EXE, channels_api.shutil.which = saved
bridge_src = (ROOT / "bridges" / "whatsapp" / "bridge.mjs").read_text(encoding="utf-8")
check("bridge.mjs sin await de nivel superior (Node SEA corre CommonJS)", not re.search(r"^await ", bridge_src, re.M))

# ======================= 4. instancia por carpeta de datos y autocomprobación =======================
sys.path.insert(0, str(ROOT / "desktop"))
import desktop_app  # noqa: E402
check("con EDITH_HOME propio, mutex y eventos llevan la huella de la carpeta",
      re.fullmatch(r"Local\\EDITH_Desktop_Quit_[0-9a-f]{8}", desktop_app.QUIT_EVENT_NAME)
      and desktop_app.MUTEX_NAME.endswith(desktop_app._SUFFIX), desktop_app.QUIT_EVENT_NAME)
saved_home = os.environ.pop("EDITH_HOME")
try:
    check("sin EDITH_HOME, los nombres de siempre (los usa el desinstalador)", desktop_app._instance_suffix() == "")
finally:
    os.environ["EDITH_HOME"] = saved_home

import self_test  # noqa: E402
report = TMP / "self-test.txt"
code = self_test.run(report)
lines = report.read_text(encoding="utf-8").splitlines()
check("autocomprobación desde el código", code == 0, lines[-1] if lines else "sin informe")
for line in lines:
    if line.startswith("[FALLO]"):
        print("    " + line)

shutil.rmtree(proj, ignore_errors=True)
raise SystemExit(summary())
