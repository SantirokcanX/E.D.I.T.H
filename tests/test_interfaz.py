"""Pruebas de la interfaz: Content-Security-Policy estricta y librerías locales (Fase 14) y el botón
▶ Ejecutar de Python (Fase 7). La parte visual (ecuaciones numeradas, números de línea, ajuste de líneas)
se comprobó en el navegador; ver "Registro de Cambios de EDITH".
Uso:  python tests/test_interfaz.py   (desde la raíz del proyecto, con el .venv activado)
"""
import os
import re
import subprocess
import sys
import time

os.environ["ML_ENABLED"] = "false"
from entorno import ROOT, TMP, Config, FakeProvider, check, sec, summary  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
import ide.code_api as code_api  # noqa: E402
import ide.server as srv  # noqa: E402

srv.provider = FakeProvider()
TOKEN = sec.get_api_token()
BASE = "http://127.0.0.1:8000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
POST = {**AUTH, "Origin": BASE}
cli = TestClient(srv.app, base_url=BASE)
STATIC = ROOT / "ide" / "static"

# ======================= 1. CSP y librerías locales =======================
r = cli.get("/", headers=AUTH)
csp = r.headers.get("content-security-policy", "")
check("la interfaz lleva una Content-Security-Policy completa", "default-src 'self'" in csp and "object-src 'none'" in csp
      and "frame-ancestors 'none'" in csp and "base-uri 'none'" in csp, csp)
script_src = re.search(r"script-src ([^;]+)", csp).group(1)
check("scripts: solo los de la propia EDITH (sin 'unsafe-inline', sin eval, sin CDN)", script_src.strip() == "'self'", script_src)
check("el WebSocket del chat está permitido solo hacia la propia EDITH", "connect-src 'self' ws://127.0.0.1:8000 wss://127.0.0.1:8000" in csp)
check("también en la API", "default-src 'self'" in cli.get("/api/version", headers=AUTH).headers.get("content-security-policy", ""))
check("un Host raro no se cuela en la política", "evil" not in srv.content_security_policy("evil.com; script-src *"))

html = (STATIC / "index.html").read_text(encoding="utf-8")
external = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(https?://[^"]+)"', html)
check("index.html no carga nada de internet (ni CDN ni Google Fonts)", not external, external)
check("sin onclick ni otros manejadores en línea (los bloquea la CSP)", not re.search(r"\son[a-z]+=", html))
check("sin <script> en línea", not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", html))
local = re.findall(r'(?:src|href)="(vendor/[^"]+)"', html)
check("todas las librerías locales existen", local and all((STATIC / p).exists() for p in local), [p for p in local if not (STATIC / p).exists()])
p = subprocess.run([sys.executable, str(ROOT / "build" / "vendor_libs.py"), "--check"], capture_output=True, text=True,
                   encoding="utf-8", cwd=ROOT)
check("las copias locales coinciden con su huella (MANIFEST.json)", p.returncode == 0, p.stdout.strip() or p.stderr[-200:])
check("versiones fijas: marked 15.0.12, mermaid 10.9.8, chart.js 4.5.1, DOMPurify 3.4.16",
      all(v in (STATIC / "vendor" / "MANIFEST.json").read_text(encoding="utf-8")
          for v in ('"marked": "15.0.12"', '"mermaid": "10.9.8"', '"chart.js": "4.5.1"', '"dompurify": "3.4.16"')))
for js in ("app.js", "render.js", "setup.js"):
    code = (STATIC / js).read_text(encoding="utf-8")
    check(f"{js}: sin eval ni new Function", "eval(" not in code and "new Function(" not in code)
check("los botones del panel Laptop usan data-app/data-vol", html.count("data-app=") == 6 and html.count("data-vol=") == 3)
gattr = (ROOT / ".gitattributes").read_text(encoding="utf-8")
check("git no cambia los finales de línea de las librerías (su huella seguiría valiendo)", "ide/static/vendor/** -text" in gattr)

# ======================= 2. ▶ Ejecutar (Python) =======================
def run(code, headers=POST, client=cli, language="python"):
    return client.post("/api/code/run", json={"code": code, "language": language}, headers=headers)


r = run("print(2 + 2, 'ñ')")
d = r.json()
check("ejecuta Python y devuelve la salida (con acentos)", r.status_code == 200 and d["stdout"].strip() == "4 ñ"
      and d["exit_code"] == 0 and not d["timed_out"], d)
check("en la carpeta workspace/ejecuciones", d["script"].startswith("ejecuciones/") and (code_api.RUN_DIR / d["script"].split("/")[1]).exists())
d = run("import sys\nprint('antes')\nraise ValueError('a propósito')").json()
check("un error se devuelve en stderr con su código de salida", d["exit_code"] == 1 and "ValueError: a propósito" in d["stderr"]
      and d["stdout"].strip() == "antes")
os.environ["HA_TOKEN"] = "secreto-que-no-debe-verse"
d = run("import os\nprint(os.environ.get('HA_TOKEN'), os.environ.get('EDITH_API_TOKEN'))").json()
check("el código no ve los secretos de EDITH", d["stdout"].strip() == "None None", d["stdout"])
d = run("import os\nprint(os.getcwd())").json()
check("se ejecuta dentro de workspace/ejecuciones", d["stdout"].strip().lower().endswith("ejecuciones"), d["stdout"])

code_api.TIMEOUT_SECONDS = 2
t0 = time.time()
d = run("import time\nprint('empiezo', flush=True)\nwhile True: time.sleep(0.1)").json()
check("si tarda demasiado se detiene (y no se queda colgado)", d["timed_out"] and time.time() - t0 < 15 and "empiezo" in d["stdout"], d)
code_api.TIMEOUT_SECONDS = 30
d = run("print('x' * 30000)").json()
check("salidas enormes se recortan", "salida recortada" in d["stdout"] and len(d["stdout"]) < 21000)

check("otra web no puede ejecutar código", run("print(1)", headers={**AUTH, "Origin": "http://sitio-ajeno.example"}).status_code == 403)
check("sin token no", run("print(1)", headers={"Origin": BASE}).status_code == 401)
Config.EDITH_ALLOWED_HOSTS = ["edith-pc"]
remote = TestClient(srv.app, base_url="http://edith-pc:8000")
check("desde otro dispositivo, aunque tenga token, no se ejecuta nada",
      run("print(1)", headers={**AUTH, "Origin": "http://edith-pc:8000"}, client=remote).status_code == 403)
Config.EDITH_ALLOWED_HOSTS = []
check("solo Python", run("console.log(1)", language="javascript").status_code == 400)
check("código vacío -> 400", run("   ").status_code == 400)

# En EDITH.exe no hay python.exe: el intérprete empaquetado ejecuta el archivo (--run-python)
sys.path.insert(0, str(ROOT / "desktop"))
import desktop_app  # noqa: E402

script = TMP / "prueba_exe.py"
script.write_text("import sys\nprint('desde EDITH.exe')\nprint('aviso', file=sys.stderr)\nsys.exit(3)\n", encoding="utf-8")
out, err = TMP / "o.txt", TMP / "e.txt"
saved = sys.stdout, sys.stderr
code = desktop_app.run_python_script([str(script), str(out), str(err)])
sys.stdout, sys.stderr = saved
check("modo --run-python (app empaquetada): salida a archivos y código de salida",
      code == 3 and out.read_text(encoding="utf-8").strip() == "desde EDITH.exe" and "aviso" in err.read_text(encoding="utf-8"))
cmd, to_files = code_api._interpreter(script, out, err)
check("desde el código usa python.exe (no pythonw, que no tiene salida)", not to_files and cmd[0].lower().endswith("python.exe"), cmd)

# ======================= 3. «Oye EDITH» con la app en la bandeja =======================
app_js = (STATIC / "app.js").read_text(encoding="utf-8")
check("al oír «Oye EDITH» con la ventana oculta, la muestra", "show_window" in app_js.split("function onWakeDetected")[1][:400])
check("la app de escritorio ofrece show_window a la interfaz", hasattr(desktop_app.DesktopApi, "show_window"))

raise SystemExit(summary())
