"""Pruebas funcionales de la Fase 15.2 (asistente de primer arranque y panel de Ajustes).
Comprueban la recomendación de modelos, la validación y el guardado de ajustes en el .env, las
descargas con progreso (contra un Ollama simulado), la bóveda, la aplicación en vivo y que solo
la propia EDITH en esta máquina pueda cambiar ajustes.
Las partes visuales (asistente en WebView2, «Elegir…», --tray) se prueban con la app real
(ver "Registro de Cambios de EDITH", v0.0.8).
Uso:  python tests/test_fase_15_2.py   (desde la raíz del proyecto, con el .venv activado)
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["ML_ENABLED"] = "false"
os.environ.pop("EDITH_DESKTOP", None)  # modo navegador salvo donde la prueba diga lo contrario
from entorno import TMP, Config, FakeProvider, check, sec, summary  # noqa: E402

# Los ajustes se escriben en un .env temporal: nunca en el del proyecto
import agent.config as config_module  # noqa: E402
ENV = TMP / "ajustes.env"
ENV.write_text("# Mi configuracion\nOLLAMA_MODEL=qwen3:4b-instruct\n# comentario que debe quedarse\nOTRA_CLAVE=sin tocar\n",
               encoding="utf-8")
config_module.env_path = ENV
Config.reload()

from dotenv import dotenv_values  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import ide.server as srv  # noqa: E402
import ide.setup_api as setup_api  # noqa: E402
from agent.setup import hardware, settings  # noqa: E402
from agent.memory.memory_manager import get_memory_manager  # noqa: E402


# ---------------------------------------------------------------- Ollama simulado
class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._json({"models": [{"name": "qwen3:4b-instruct", "size": 2_684_354_560},
                                   {"name": "llama3:latest", "size": 4_000_000_000}]})
        elif self.path == "/api/version":
            self._json({"version": "0.0-prueba"})
        else:
            self._json({"error": "no"}, 404)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        model = data.get("model", "")
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def send(ev):
            self.wfile.write((json.dumps(ev) + "\n").encode())
            self.wfile.flush()

        try:
            if model.startswith("roto"):
                send({"error": "pull model manifest: file does not exist"})
                return
            steps = 60 if model.startswith("lento") else 4
            send({"status": "pulling manifest"})
            for i in range(steps + 1):
                send({"status": "pulling abc", "digest": "sha256:abc", "total": 1000, "completed": 1000 * i // steps})
                time.sleep(0.05 if model.startswith("lento") else 0.01)
            send({"status": "verifying sha256 digest"})
            send({"status": "success"})
        except ConnectionError:
            pass  # EDITH cortó la descarga (pausa): es lo esperado


ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=ollama.serve_forever, daemon=True).start()
OLLAMA_URL = f"http://127.0.0.1:{ollama.server_address[1]}"
os.environ["OLLAMA_BASE_URL"] = OLLAMA_URL
Config.OLLAMA_BASE_URL = OLLAMA_URL
setup_api._pulls.base_url = OLLAMA_URL

fake = FakeProvider()
srv.provider = fake
srv.edith_agent.provider = fake
srv.ml_engine = None

TOKEN = sec.get_api_token()
BASE = "http://127.0.0.1:8000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
POST = {**AUTH, "Origin": BASE}


def cli(base_url=BASE):
    return TestClient(srv.app, base_url=base_url)


def env_text():
    return ENV.read_text(encoding="utf-8")


def save(values, headers=POST, base_url=BASE):
    return cli(base_url).post("/api/settings", json={"values": values}, headers=headers)


# ======================= 1. Recomendación de modelos =======================
rec = hardware.recommend
check("24 GB de VRAM -> qwen3:14b + qwen3:32b", (rec(24, True, 64)["fast"], rec(24, True, 64)["deep"]) == ("qwen3:14b", "qwen3:32b"))
check("16 GB -> qwen3:8b + qwen3:14b", (rec(16, True, 32)["fast"], rec(16, True, 32)["deep"]) == ("qwen3:8b", "qwen3:14b"))
check("12 GB -> qwen3:8b para los dos modos", (rec(12, True, 32)["fast"], rec(12, True, 32)["deep"]) == ("qwen3:8b", "qwen3:8b"))
check("6 GB (esta laptop) -> qwen3:4b-instruct + qwen3:4b",
      (rec(6, True, 16)["fast"], rec(6, True, 16)["deep"]) == ("qwen3:4b-instruct", "qwen3:4b"))
check("sin GPU dedicada (aunque la integrada reporte 8 GB) -> qwen3:1.7b", rec(8, False, 16)["fast"] == "qwen3:1.7b")
check("menos de 8 GB de RAM baja a los modelos pequeños", rec(16, True, 6)["fast"] == "qwen3:1.7b")
check("GPU dedicada vs integrada se distinguen por nombre",
      hardware._is_dedicated("NVIDIA GeForce RTX 4050 Laptop GPU") and hardware._is_dedicated("AMD Radeon RX 7800 XT")
      and hardware._is_dedicated("Intel(R) Arc(TM) A770 Graphics")
      and not hardware._is_dedicated("AMD Radeon 760M Graphics") and not hardware._is_dedicated("Intel(R) UHD Graphics"))
check("«modelo:latest» cuenta como instalado sin la etiqueta", "llama3" in hardware.installed_names([{"name": "llama3:latest"}]))

r = cli().get("/api/setup/hardware?fast=qwen3:4b-instruct&deep=qwen3:4b", headers=AUTH)
d = r.json() if r.status_code == 200 else {}
check("diagnóstico: Ollama activo con sus modelos", d.get("ollama", {}).get("running") and d["ollama"]["version"] == "0.0-prueba",
      d.get("ollama"))
check("diagnóstico: solo falta el modelo no instalado y calcula cuánto descargar",
      d.get("models_needed") == ["qwen3:4b"] and d.get("download_gb") == 2.5, (d.get("models_needed"), d.get("download_gb")))
check("diagnóstico: CPU, RAM y disco de los modelos", d.get("system", {}).get("ram_gb", 0) > 0
      and d.get("models_disk", {}).get("free_gb", -1) >= 0 and "disk_ok" in d)

# ======================= 2. Primer arranque =======================
st = cli().get("/api/setup/status", headers=AUTH).json()
check("el asistente está pendiente en un EDITH nuevo (y no es la app de escritorio)", not st["completed"] and not st["desktop"], st)
check("sin token no se ve el estado del asistente (Fase 14)", cli().get("/api/setup/status").status_code == 401)
check("otra web no puede marcar el asistente como hecho",
      cli().post("/api/setup/complete", headers={**AUTH, "Origin": "http://sitio-ajeno.example"}).status_code == 403)
check("la propia EDITH sí", cli().post("/api/setup/complete", headers=POST).status_code == 200
      and cli().get("/api/setup/status", headers=AUTH).json()["completed"])
check("queda guardado en EDITH_HOME/setup.json", settings.SETUP_FILE.exists() and str(TMP) in str(settings.SETUP_FILE))

# ======================= 3. Leer ajustes =======================
os.environ["TWILIO_AUTH_TOKEN"] = "secreto-de-prueba"
g = cli().get("/api/settings", headers=AUTH).json()
keys = [f["key"] for s in g["schema"] for f in s["fields"]]
check("7 secciones de Ajustes", [s["id"] for s in g["schema"]] ==
      ["perfil", "modelos", "obsidian", "voz", "canales", "autonomia", "avanzado"])
check("«Iniciar con Windows» no aparece fuera de la app de escritorio", "START_WITH_WINDOWS" not in keys)
check("el Auth Token de Twilio llega enmascarado", g["values"]["TWILIO_AUTH_TOKEN"] == settings.MASK)
check("el .env que se edita es el temporal de la prueba", g["env_file"] == str(ENV), g["env_file"])

# ======================= 4. Guardar y validar =======================
r = save({"AUTHORIZED_PHONE_NUMBERS": "+52 1 55 1234 5678, (521) 55-8765-4321\n+5215512345678",
          "PUBLIC_BASE_URL": "https://edith.ejemplo.mx/", "QUIET_HOURS": "23:00 - 07:00",
          "OLLAMA_MODEL": "qwen3:8b", "EDITH_PORT": "8123"})
t, v = env_text(), dotenv_values(ENV)
check("guardar ajustes válidos -> 200", r.status_code == 200, r.text[:200])
check("números normalizados, sin duplicados",
      v.get("AUTHORIZED_PHONE_NUMBERS") == "+5215512345678,+5215587654321", v.get("AUTHORIZED_PHONE_NUMBERS"))
check("URL pública sin barra final y horas de silencio normalizadas",
      v.get("PUBLIC_BASE_URL") == "https://edith.ejemplo.mx" and v.get("QUIET_HOURS") == "23:00-07:00",
      (v.get("PUBLIC_BASE_URL"), v.get("QUIET_HOURS")))
check("se conservan los comentarios y las demás claves del .env",
      "# comentario que debe quedarse" in t and v.get("OTRA_CLAVE") == "sin tocar" and t.count("OLLAMA_MODEL=") == 1)
check("Config se recarga con lo nuevo", Config.OLLAMA_MODEL == "qwen3:8b"
      and Config.AUTHORIZED_PHONE_NUMBERS == ["5215512345678", "5215587654321"], Config.AUTHORIZED_PHONE_NUMBERS)
check("cambiar el puerto avisa que hay que reiniciar", r.json().get("restart_required") == ["EDITH_PORT"], r.json())

for values, key, why in [
    ({"AUTHORIZED_PHONE_NUMBERS": "55 1234"}, "AUTHORIZED_PHONE_NUMBERS", "número demasiado corto"),
    ({"PUBLIC_BASE_URL": "http://edith.ejemplo.mx"}, "PUBLIC_BASE_URL", "URL pública sin HTTPS"),
    ({"MORNING_BRIEFING_TIME": "25:00"}, "MORNING_BRIEFING_TIME", "hora imposible"),
    ({"EDITH_PORT": "80"}, "EDITH_PORT", "puerto reservado"),
    ({"OBSIDIAN_VAULT_PATH": "mis notas"}, "OBSIDIAN_VAULT_PATH", "ruta relativa"),
    ({"OLLAMA_NUM_CTX": "100"}, "OLLAMA_NUM_CTX", "contexto fuera de rango"),
    ({"EDITH_VOICE": "voz-inventada"}, "EDITH_VOICE", "voz que no existe"),
    ({"HEARTBEAT_NEWS_TOPICS": "ia\nREMOTE_ALLOW_SYSTEM_TOOLS=true"}, "HEARTBEAT_NEWS_TOPICS", "salto de línea (colar otra clave)"),
]:
    before = env_text()
    r = save(values)
    errs = r.json().get("detail", {}) if r.status_code == 400 else {}
    check(f"rechaza {why} con mensaje claro", r.status_code == 400 and key in errs and env_text() == before,
          (r.status_code, errs.get(key)))
check("ninguna inyección activó PowerShell remoto", "REMOTE_ALLOW_SYSTEM_TOOLS" not in env_text()
      and not Config.REMOTE_ALLOW_SYSTEM_TOOLS)

before = env_text()
r = save({"CLAVE_INVENTADA": "x", "PATH": "C:\\malo"})
check("claves desconocidas se ignoran (nada arbitrario llega al .env)", r.status_code == 200
      and "CLAVE_INVENTADA" not in env_text() and "PATH=" not in env_text())

r = save({"TWILIO_AUTH_TOKEN": settings.MASK})
check("dejar el token enmascarado no lo cambia", r.status_code == 200 and "TWILIO_AUTH_TOKEN" not in r.json()["changed"]
      and os.environ["TWILIO_AUTH_TOKEN"] == "secreto-de-prueba")
r = save({"TWILIO_AUTH_TOKEN": "token-nuevo"})
check("escribir uno nuevo sí lo guarda", dotenv_values(ENV).get("TWILIO_AUTH_TOKEN") == "token-nuevo")

r = save({"USER_NAME": "Diego"})
check("el nombre va a la memoria a largo plazo (no al .env)", r.status_code == 200
      and get_memory_manager().long_term_data.get("user_name") == "Diego" and "USER_NAME" not in env_text())

before_run = settings.get_start_with_windows()
r = save({"START_WITH_WINDOWS": not before_run})
after_run = settings.get_start_with_windows()
if after_run != before_run:  # no debería pasar; si pasa, dejar el registro como estaba
    settings.set_start_with_windows(before_run)
check("fuera de la app de escritorio no se toca el inicio de Windows", r.status_code == 200 and after_run == before_run)

# ======================= 5. Solo desde esta máquina y desde la propia EDITH =======================
check("otra web no puede cambiar ajustes", save({"USER_NAME": "x"}, headers={**AUTH, "Origin": "http://sitio-ajeno.example"}).status_code == 403)
check("otro puerto local tampoco", save({"USER_NAME": "x"}, headers={**AUTH, "Origin": "http://127.0.0.1:3000"}).status_code == 403)
check("sin token -> 401", save({"USER_NAME": "x"}, headers={"Origin": BASE}).status_code == 401)
check("Host ajeno -> rechazado", save({"USER_NAME": "x"}, headers={**AUTH, "Origin": "http://evil.example"},
                                      base_url="http://evil.example").status_code in (400, 403))
Config.EDITH_ALLOWED_HOSTS = ["edith-pc"]
r = save({"USER_NAME": "x"}, headers={**AUTH, "Origin": "http://edith-pc:8000"}, base_url="http://edith-pc:8000")
check("desde otro dispositivo (aunque tenga token) los ajustes no se cambian", r.status_code == 403, r.status_code)
check("...pero el resto de EDITH sí responde ahí", cli("http://edith-pc:8000").get("/api/status", headers=AUTH).status_code == 200)
Config.EDITH_ALLOWED_HOSTS = []

# ======================= 6. Aplicar en vivo =======================
class LiveProvider:
    def __init__(self):
        self.model, self.deep_model, self.think = "a", None, "auto"
        self.num_ctx, self.keep_alive, self.base_url = 8192, "30m", OLLAMA_URL
        self._no_tools, self._no_think = {"x"}, {"y"}
        self.warmed = threading.Event()

    def warmup(self):
        self.warmed.set()


live = LiveProvider()
srv.provider = live
r = save({"OLLAMA_MODEL": "qwen3:14b", "OLLAMA_DEEP_MODEL": "qwen3:32b", "OLLAMA_NUM_CTX": "16384"})
check("cambiar modelos se aplica sin reiniciar", r.status_code == 200 and "modelos" in r.json()["applied"]
      and (live.model, live.deep_model, live.num_ctx) == ("qwen3:14b", "qwen3:32b", 16384), r.json())
check("...limpia las cachés del proveedor y precarga el modelo nuevo",
      not live._no_tools and not live._no_think and live.warmed.wait(3))
r = save({"OLLAMA_DEEP_MODEL": "qwen3:14b"})
check("si el profundo es el mismo que el rápido, se usa uno solo", live.deep_model is None)
srv.provider = fake

voice = sorted(srv.voice_engine.VOICES)[-1]
r = save({"EDITH_VOICE": voice})
check("cambiar la voz se aplica sin reiniciar", r.status_code == 200 and "voz" in r.json()["applied"]
      and srv.voice_engine.voice_key == voice, (r.json().get("applied"), getattr(srv.voice_engine, "voice_key", None)))

# ======================= 7. Descarga de modelos =======================
r = cli().post("/api/setup/models/pull", json={"models": []}, headers=POST)
check("descargar sin modelos -> 400", r.status_code == 400)
check("otra web no puede lanzar descargas",
      cli().post("/api/setup/models/pull", json={"models": ["x:1b"]}, headers={**AUTH, "Origin": "http://sitio-ajeno.example"}).status_code == 403)
r = cli().post("/api/setup/models/pull", json={"models": ["qwen3:4b", "qwen3:4b"]}, headers=POST)
seen = []
for _ in range(100):
    p = cli().get("/api/setup/models/progress", headers=AUTH).json()
    seen.append(p["percent"])
    if p["finished"]:
        break
    time.sleep(0.05)
check("descarga completa con progreso (duplicados juntos)", p["ok"] and p["percent"] == 100.0
      and [i["model"] for i in p["items"]] == ["qwen3:4b"] and p["items"][0]["status"] == "listo", p)

cli().post("/api/setup/models/pull", json={"models": ["lento:1b", "qwen3:1.7b"]}, headers=POST)
time.sleep(0.6)
busy = cli().post("/api/setup/models/pull", json={"models": ["otro:1b"]}, headers=POST).status_code
mid = cli().get("/api/setup/models/progress", headers=AUTH).json()
cli().post("/api/setup/models/cancel", headers=POST)
for _ in range(60):
    p = cli().get("/api/setup/models/progress", headers=AUTH).json()
    if p["finished"]:
        break
    time.sleep(0.05)
check("solo una descarga a la vez -> 409", busy == 409)
check("el porcentaje avanza mientras descarga", 0 < mid["percent"] < 100, mid["percent"])
check("pausar detiene la descarga y la siguiente queda cancelada",
      [i["status"] for i in p["items"]] == ["cancelado", "cancelado"] and not p["ok"], [i["status"] for i in p["items"]])

cli().post("/api/setup/models/pull", json={"models": ["roto:1b"]}, headers=POST)
for _ in range(60):
    p = cli().get("/api/setup/models/progress", headers=AUTH).json()
    if p["finished"]:
        break
    time.sleep(0.05)
check("un modelo que no existe muestra el error de Ollama", p["items"][0]["status"] == "error"
      and "does not exist" in p["items"][0]["message"], p["items"][0])

# ======================= 8. Bóveda de Obsidian =======================
r = cli().post("/api/setup/vault/check", json={"path": "notas"}, headers=POST)
check("ruta relativa de la bóveda -> 400", r.status_code == 400)
nueva = TMP / "boveda nueva"
r = cli().post("/api/setup/vault/check", json={"path": str(nueva)}, headers=POST).json()
check("carpeta inexistente: lo dice sin crearla", not r["exists"] and not nueva.exists())
r = cli().post("/api/setup/vault/check", json={"path": str(nueva), "create": True}, headers=POST).json()
check("«Crear carpetas» deja la estructura 00-04 lista y se puede escribir",
      r["exists"] and r["has_structure"] and r["writable"] and r["notes"] == 0, r)
(nueva / ".obsidian").mkdir()
(nueva / "00 - Dashboard" / "Inicio.md").write_text("hola", encoding="utf-8")
r = cli().post("/api/setup/vault/check", json={"path": str(nueva)}, headers=POST).json()
check("reconoce una bóveda de Obsidian y cuenta sus notas", r["is_obsidian"] and r["notes"] == 1, r)
check("no deja el archivo de prueba de escritura", not (nueva / ".edith_prueba_escritura").exists())
check("otra web no puede crear carpetas",
      cli().post("/api/setup/vault/check", json={"path": str(TMP / "x"), "create": True},
                 headers={**AUTH, "Origin": "http://sitio-ajeno.example"}).status_code == 403 and not (TMP / "x").exists())

# ======================= 9. Modo escritorio =======================
os.environ["EDITH_DESKTOP"] = "1"
g = cli().get("/api/settings", headers=AUTH).json()
check("en la app de escritorio aparece «Iniciar con Windows»",
      "START_WITH_WINDOWS" in [f["key"] for s in g["schema"] for f in s["fields"]])
check("...y el estado del asistente lo indica", cli().get("/api/setup/status", headers=AUTH).json()["desktop"])
os.environ.pop("EDITH_DESKTOP", None)

ollama.shutdown()
raise SystemExit(summary())
