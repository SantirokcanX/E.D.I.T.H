"""Pruebas de la Fase 15.3 (empaquetado): versión única, modo congelado, bridge empaquetado,
autocomprobación y enlace de acceso para otro dispositivo sin main.py. El ejecutable de verdad (dist/EDITH/EDITH.exe) se prueba con
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

# ======================= 5. enlace de acceso para otro dispositivo (sin main.py en EDITH.exe) =======================
import io  # noqa: E402
from urllib.parse import urlsplit  # noqa: E402

import ide.auth as auth  # noqa: E402
from agent.config import Config  # noqa: E402

TOKEN = get_api_token()
BASE = "http://127.0.0.1:8000"
UI = {"Cookie": f"edith_token_8000={TOKEN}", "Origin": BASE}  # lo que manda la interfaz al pulsar el botón


def link_cli(**kw):
    return TestClient(srv.app, base_url=kw.pop("base_url", BASE), **kw)


def local_cli():
    return link_cli(client=("127.0.0.1", 50000))  # el navegador de esta misma máquina


saved_frozen = auth.FROZEN
try:
    auth.FROZEN = True
    page = link_cli().get("/").text
    check("EDITH.exe: la página de acceso ya no menciona main.py",
          "main.py" not in page and "Copiar enlace para otro dispositivo" in page and "EDITH.exe --access-link" in page)
    check("EDITH.exe: el aviso de arranque tampoco", "main.py" not in auth.access_link_hint()
          and "Ajustes › Avanzado" in auth.access_link_hint(), auth.access_link_hint())
    check("EDITH.exe: el texto de --access-link tampoco", "main.py" not in auth.access_links_text(8000))
    auth.FROZEN = False
    page = link_cli().get("/").text
    check("desde el código: Ajustes, python main.py --access-link y el puerto real",
          "Copiar enlace para otro dispositivo" in page and "python main.py --access-link" in page
          and "http://localhost:8000" in page)
    check("desde el código, el aviso de arranque sigue citando main.py", "python main.py --access-link" in auth.access_link_hint())
finally:
    auth.FROZEN = saved_frozen
server_src = (ROOT / "ide" / "server.py").read_text(encoding="utf-8")
check("el aviso de arranque del servidor sale de access_link_hint (sin main.py fijo)",
      "access_link_hint()" in server_src and "main.py --access-link" not in server_src)

Config.PUBLIC_BASE_URL, Config.EDITH_ALLOWED_HOSTS = "", []
r = local_cli().post("/api/setup/access-link", headers=UI)
data = r.json() if r.status_code == 200 else {}
check("Ajustes › Avanzado: el botón obtiene el enlace (cookie + Origin propio, desde esta máquina)",
      r.status_code == 200 and data.get("local") == f"http://localhost:8000/?token={TOKEN}", r.text[:120])
check("... sin guardarse en caché", r.headers.get("cache-control") == "no-store", r.headers.get("cache-control"))
check("sin URL pública ni hosts extra: no hay enlace remoto y explica cómo conseguirlo",
      data.get("remote") == [] and "PUBLIC_BASE_URL" not in data.get("no_remote", "")
      and "URL pública HTTPS" in data.get("no_remote", "") and "EDITH_ALLOWED_HOSTS" in data.get("no_remote", ""))

Config.PUBLIC_BASE_URL, Config.EDITH_ALLOWED_HOSTS = "https://edith.example", ["edith-pc"]
data = local_cli().post("/api/setup/access-link", headers=UI).json()
check("con URL pública y EDITH_ALLOWED_HOSTS: un enlace por cada uno, la URL pública primero",
      data.get("remote") == [f"https://edith.example/?token={TOKEN}", f"http://edith-pc:8000/?token={TOKEN}"], data.get("remote"))
remote = data["remote"][0]
r = link_cli(base_url="https://edith.example").get(remote[len("https://edith.example"):], follow_redirects=False)
check("el enlace copiado abre EDITH desde el otro dispositivo (303 + cookie)",
      r.status_code == 303 and "set-cookie" in r.headers, r.status_code)

check("el botón sin token -> 401", local_cli().post("/api/setup/access-link", headers={"Origin": BASE}).status_code == 401)
check("desde otra web (Origin ajeno) -> 403", local_cli().post(
    "/api/setup/access-link", headers={**UI, "Origin": "https://evil.example"}).status_code == 403)
check("desde otro dispositivo, aunque tenga el token -> 403",
      link_cli().post("/api/setup/access-link", headers=BEARER).status_code == 403)
check("a través de un túnel o proxy (X-Forwarded-For) -> 403", local_cli().post(
    "/api/setup/access-link", headers={**UI, "X-Forwarded-For": "203.0.113.9"}).status_code == 403)
check("con el Host público (aunque llegue a 127.0.0.1) -> 403", local_cli().post(
    "/api/setup/access-link", headers={**BEARER, "Host": "edith.example"}).status_code == 403)
r = local_cli().get("/api/setup/access-link", headers=UI)
check("solo POST (un GET no lo devuelve)", r.status_code in (404, 405) and TOKEN not in r.text, r.status_code)

saved_frozen = auth.FROZEN
try:
    auth.FROZEN = True
    text = auth.access_links_text(8000)
finally:
    auth.FROZEN = saved_frozen
check("texto de --access-link: enlaces remotos y cómo entrar desde esta computadora",
      f"https://edith.example/?token={TOKEN}" in text and "la app de EDITH" in text and "no lo compartas" in text, text)
check("... y se puede escribir en una consola o archivo cp1252 (sin emojis ni flechas)",
      text.encode("cp1252") and auth.access_link_hint().encode("cp1252") and auth.NO_REMOTE_ACCESS.encode("cp1252"))
Config.PUBLIC_BASE_URL, Config.EDITH_ALLOWED_HOSTS = "", []
check("sin enlaces remotos, el texto lo explica", auth.NO_REMOTE_ACCESS in auth.access_links_text(8000))

out = io.StringIO()
code = desktop_app.show_access_links(out)
check("EDITH.exe --access-link escribe el texto en la terminal",
      code == 0 and out.getvalue().startswith("Enlace de acceso a EDITH") and auth.NO_REMOTE_ACCESS in out.getvalue(),
      out.getvalue()[:80])
calls = []
saved = (sys.argv, desktop_app.show_access_links, desktop_app.setup_logging, desktop_app.acquire_single_instance)
try:
    sys.argv = ["EDITH.exe", "--access-link"]
    desktop_app.show_access_links = lambda: calls.append("enlace") or 0
    desktop_app.setup_logging = lambda: calls.append("registro")
    desktop_app.acquire_single_instance = lambda: calls.append("instancia") or False
    try:
        desktop_app.main()
        exit_code = None
    except SystemExit as e:
        exit_code = e.code
finally:
    sys.argv, desktop_app.show_access_links, desktop_app.setup_logging, desktop_app.acquire_single_instance = saved
check("EDITH.exe --access-link no abre la app ni toca la instancia abierta", calls == ["enlace"] and exit_code == 0,
      (calls, exit_code))

setup_js = (ROOT / "ide" / "static" / "setup.js").read_text(encoding="utf-8")
check("Ajustes tiene el botón «Copiar enlace para otro dispositivo» (POST, token oculto en pantalla)",
      "Copiar enlace para otro dispositivo" in setup_js and '"/api/setup/access-link", { method: "POST" }' in setup_js
      and "maskToken" in setup_js)
static_texts = [p.read_text(encoding="utf-8") for p in (ROOT / "ide" / "static").glob("*.*") if p.suffix in (".js", ".html")]
check("ningún texto de la interfaz menciona main.py", not any("main.py" in t for t in static_texts))
os.environ["EDITH_API_TOKEN"] = "clave+con/signos=raros&mas"  # EDITH_API_TOKEN lo elige el usuario
try:
    link = auth.local_access_link(8000)
    r = link_cli().get(link[len("http://localhost:8000"):], follow_redirects=False)
    check("un EDITH_API_TOKEN con + / = & sigue dando un enlace que funciona",
          urlsplit(link).query == "token=clave%2Bcon%2Fsignos%3Draros%26mas" and r.status_code == 303, (link, r.status_code))
finally:
    os.environ.pop("EDITH_API_TOKEN")

shutil.rmtree(proj, ignore_errors=True)
raise SystemExit(summary())
