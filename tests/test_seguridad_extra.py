"""Pruebas de lo que faltaba de la Fase 14: secretos cifrados con DPAPI, límite de peticiones,
confirmación por WhatsApp para acciones pedidas desde el celular y datos personales fuera de git.
Uso:  python tests/test_seguridad_extra.py   (desde la raíz del proyecto, con el .venv activado)
"""
import asyncio
import os
import subprocess
import sys
import threading
import time

os.environ["ML_ENABLED"] = "false"
from entorno import ROOT, TMP, Config, FakeProvider, check, sec, summary  # noqa: E402

import agent.config as config_module  # noqa: E402
ENV = TMP / "ajustes.env"
ENV.write_text("# prueba\n", encoding="utf-8")
config_module.env_path = ENV
Config.reload()

from dotenv import dotenv_values  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402
import agent.core.reasoning_agent as rag  # noqa: E402
import ide.channels_api as channels_api  # noqa: E402
import ide.server as srv  # noqa: E402
from agent import ratelimit, secret_store  # noqa: E402
from agent.channels import whatsapp  # noqa: E402
from agent.setup import settings  # noqa: E402

fake = FakeProvider()
srv.provider = fake
srv.edith_agent.provider = fake
srv.ml_engine = None
channels_api._state["provider"] = fake
TOKEN = sec.get_api_token()
BASE = "http://127.0.0.1:8000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

# ======================= 1. Secretos cifrados con DPAPI =======================
enc = secret_store.protect("mi-secreto-ñ")
check("DPAPI: el texto cifrado no contiene el secreto y lleva el prefijo",
      enc.startswith("dpapi:") and "mi-secreto" not in enc)
check("DPAPI: se descifra igual (con acentos)", secret_store.unprotect(enc) == "mi-secreto-ñ")
check("un valor sin prefijo es texto plano (.env escrito a mano)", secret_store.unprotect("abc") == "abc")
check("un valor corrupto no revienta: vuelve vacío para regenerarlo", secret_store.unprotect("dpapi:QUJD") == "")
check("cifrar dos veces no anida", secret_store.protect(enc) == enc)

stored = sec.API_TOKEN_FILE.read_text(encoding="utf-8")
check("el token de acceso se guarda cifrado en disco", stored.startswith("dpapi:") and TOKEN not in stored)
check("y se lee igual en cada llamada", sec.get_api_token() == TOKEN)
legacy = "x" * 43
sec.API_TOKEN_FILE.write_text(legacy, encoding="utf-8")  # archivo de una versión anterior (texto plano)
check("un token antiguo en texto plano sigue valiendo...", sec.get_api_token() == legacy)
check("...y queda cifrado al leerlo", sec.API_TOKEN_FILE.read_text(encoding="utf-8").startswith("dpapi:")
      and sec.get_api_token() == legacy)
sec.API_TOKEN_FILE.write_text(secret_store.protect(TOKEN), encoding="utf-8")

bridge_secret = sec.get_bridge_secret()
check("la clave del bridge también va cifrada", sec.BRIDGE_SECRET_FILE.read_text(encoding="utf-8").startswith("dpapi:"))
captured = {}
_real_popen, _real_bridge_command = subprocess.Popen, channels_api.bridge_command
channels_api.bridge_command = lambda: (["node", "bridge.mjs"], TMP)
channels_api.subprocess.Popen = lambda args, **kw: captured.update(kw) or type("P", (), {"poll": lambda s: None})()
channels_api._start_bridge(8000)
check("EDITH pasa la clave al bridge en EDITH_BRIDGE_SECRET (en claro, solo en memoria)",
      captured.get("env", {}).get("EDITH_BRIDGE_SECRET") == bridge_secret)
channels_api.subprocess.Popen = _real_popen
channels_api.bridge_command = _real_bridge_command
channels_api._state["bridge"] = None

data_dir = TMP / "bridge_data"
(data_dir / "channels").mkdir(parents=True)
(data_dir / "channels" / "bridge_secret").write_text(secret_store.protect("y" * 43), encoding="utf-8")
env = {k: v for k, v in os.environ.items() if k != "EDITH_BRIDGE_SECRET"}
env.update(EDITH_DATA_DIR=str(data_dir), EDITH_URL="http://127.0.0.1:9")
try:
    p = subprocess.run(["node", str(ROOT / "bridges" / "whatsapp" / "bridge.mjs")], cwd=str(ROOT / "bridges" / "whatsapp"),
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    check("el bridge suelto no usa la clave cifrada como si fuera la clave (se detiene y lo explica)",
          p.returncode == 1 and "cifrada" in p.stderr, (p.returncode, p.stderr[-160:]))
except FileNotFoundError:
    check("el bridge suelto se detiene con la clave cifrada (sin Node: se omite)", True)

r = settings.save({"TWILIO_AUTH_TOKEN": "token-twilio-secreto"})
raw = dotenv_values(ENV).get("TWILIO_AUTH_TOKEN", "")
check("Ajustes guarda los secretos cifrados en el .env", r["ok"] and raw.startswith("dpapi:")
      and "token-twilio-secreto" not in ENV.read_text(encoding="utf-8"), raw[:20])
check("en memoria EDITH los usa en claro", os.environ["TWILIO_AUTH_TOKEN"] == "token-twilio-secreto"
      and Config.TWILIO_AUTH_TOKEN == "token-twilio-secreto")
os.environ["TWILIO_AUTH_TOKEN"] = "otra-cosa"
Config.reload()
check("al recargar el .env se descifra solo", Config.TWILIO_AUTH_TOKEN == "token-twilio-secreto")
r = settings.save({"TWILIO_PHONE_NUMBER": "+15551234567"})
check("los campos que no son secretos siguen en claro", dotenv_values(ENV).get("TWILIO_PHONE_NUMBER") == "+15551234567")

# ======================= 2. Límite de peticiones =======================
w = ratelimit.SlidingWindow("PRUEBA_LIMITE", window=1.0)
Config.PRUEBA_LIMITE = 3
hits = [w.hit("a") for _ in range(4)]
check("ventana: 3 permitidas y la 4.ª no", hits == [True, True, True, False], hits)
check("otra clave tiene su propia cuenta", w.hit("b"))
time.sleep(1.05)
check("pasado el minuto (aquí 1 s) vuelve a dejar", w.hit("a"))
Config.PRUEBA_LIMITE = 0
check("límite 0 = sin límite", all(w.hit("a") for _ in range(50)))

Config.EDITH_ALLOWED_HOSTS = ["edith-pc"]
Config.RATE_LIMIT_PER_MINUTE = 5
ratelimit.reset_all()
remote = TestClient(srv.app, base_url="http://edith-pc:8000", client=("100.64.0.7", 50000))
codes = [remote.get("/api/version", headers=AUTH).status_code for _ in range(7)]
check("desde otro dispositivo: 5 peticiones y luego 429", codes == [200] * 5 + [429] * 2, codes)
r = remote.get("/api/version", headers=AUTH)
check("el 429 dice cuándo reintentar (Retry-After)", r.status_code == 429 and int(r.headers.get("retry-after", 0)) >= 1)
local = TestClient(srv.app, base_url=BASE, client=("127.0.0.1", 50001))
check("la propia laptop no tiene ese límite", all(local.get("/api/version", headers=AUTH).status_code == 200 for _ in range(20)))

Config.RATE_LIMIT_PER_MINUTE = 1000
Config.AUTH_FAILURES_PER_MINUTE = 3
ratelimit.reset_all()
bad = {"Authorization": "Bearer " + "z" * 43}
codes = [remote.get("/api/version", headers=bad).status_code for _ in range(3)]
check("3 tokens incorrectos -> 401", codes == [401, 401, 401], codes)
check("al 4.º intento esa IP espera, aunque ahora traiga el token bueno",
      remote.get("/api/version", headers=AUTH).status_code == 429)
other = TestClient(srv.app, base_url="http://edith-pc:8000", client=("100.64.0.8", 50000))
check("otra IP no se ve afectada", other.get("/api/version", headers=AUTH).status_code == 200)
check("un enlace con token falso también cuenta", other.get("/?token=" + "q" * 43).status_code == 401
      and ratelimit.auth_failures.blocked("100.64.0.8") is False)
for _ in range(5):
    local.get("/api/version", headers=bad)
check("en la laptop un token viejo no bloquea (no cuenta como ataque)",
      local.get("/api/version", headers=AUTH).status_code == 200)
Config.EDITH_ALLOWED_HOSTS = []
Config.AUTH_FAILURES_PER_MINUTE = 10
ratelimit.reset_all()

Config.CHAT_LIMIT_PER_MINUTE = 2
errors = []
with local.websocket_connect("ws://127.0.0.1:8000/ws/chat", headers={**AUTH, "Origin": BASE}) as ws:
    for i in range(3):
        ws.send_json({"action": "query", "prompt": f"hola {i}", "mode": "standard", "reasoning": "fast", "speak": False})
    deadline = time.time() + 20
    finals = 0
    while time.time() < deadline and (finals < 2 or not errors):
        m = ws.receive_json()
        if m.get("type") == "error":
            errors.append(m.get("message", ""))
        if m.get("type") == "final_answer":
            finals += 1
check("chat: la 3.ª consulta en el mismo minuto se rechaza con un aviso claro",
      any("Vas muy rápido" in e for e in errors), errors[:2])
Config.CHAT_LIMIT_PER_MINUTE = 20
ratelimit.reset_all()

# ======================= 3. Confirmación por WhatsApp =======================
ans = whatsapp._confirmation_answer
check("«SI 4821», «sí, 4821» y «4821» autorizan",
      ans("si 4821", "4821") is True and ans(whatsapp._norm("Sí, 4821!"), "4821") is True and ans("4821", "4821") is True)
check("«no» o «cancela» rechazan", ans("no", "4821") is False and ans("cancela eso", "4821") is False)
check("un «sí» suelto, otro código u otra frase no autorizan",
      ans("si", "4821") is None and ans("si 1234", "4821") is None and ans("si claro hazlo 4821 ya", "4821") is None)

Config.WHATSAPP_ENABLED = True
Config.REMOTE_ALLOW_SYSTEM_TOOLS = True
Config.AUTHORIZED_PHONE_NUMBERS = ["525511112222"]
SENDER = "525511112222"
sent = []
whatsapp.send_whatsapp = lambda text="", audio_ogg=None, to=None: sent.append((to, text)) or True
executed = []
rag.run_system_command = lambda command: executed.append(command) or "hola desde powershell"


def inbound(text):
    return asyncio.run(whatsapp.handle_inbound(fake, {"from": SENDER, "text": text}))


def ask_in_background(text):
    out = {}
    t = threading.Thread(target=lambda: out.update(inbound(text)), daemon=True)
    t.start()
    for _ in range(100):
        if any("SI " in m for _, m in sent):
            break
        time.sleep(0.05)
    return t, out


sent.clear()
t, first = ask_in_background("ejecuta en powershell echo hola")
question = next((m for _, m in sent if "SI " in m), "")
code = question.split("*SI ")[1].split("*")[0] if "*SI " in question else ""
check("pedir PowerShell por WhatsApp manda la pregunta con el comando y un código de 4 dígitos",
      "echo hola" in question and len(code) == 4 and code.isdigit() and sent[0][0] == SENDER, question[:120])
check("mientras tanto no se ejecuta nada", executed == [])
r = inbound("ok")
check("otra respuesta no autoriza: recuerda el código", f"SI {code}" in r.get("reply_text", "") and executed == [])
r = inbound(f"Sí {code}")
t.join(15)
check("«SI <código>» autoriza", r.get("reply_text", "").startswith("✅"), r.get("reply_text"))
check("y se ejecuta una sola vez, con la respuesta en el chat",
      executed == ["echo hola"] and "hola desde powershell" in first.get("reply_text", ""), (executed, first.get("reply_text", "")[:80]))

sent.clear(); executed.clear()
t, first = ask_in_background("ejecuta en powershell echo hola")
r = inbound("no")
t.join(15)
check("«NO» cancela y no se ejecuta", r.get("reply_text", "").startswith("❌") and executed == [])
check("el modelo sabe que no se autorizó", "NO autorizó" in first.get("reply_text", "") or "no autoriz" in first.get("reply_text", "").lower(),
      first.get("reply_text", "")[:120])

sent.clear(); executed.clear()
whatsapp.CONFIRM_TIMEOUT = 0.5
first = inbound("ejecuta en powershell echo hola")
check("sin respuesta caduca, avisa y no ejecuta", executed == [] and any("⌛" in m for _, m in sent), [m[:30] for _, m in sent])
check("ya no queda nada pendiente", SENDER not in whatsapp._pending)
whatsapp.CONFIRM_TIMEOUT = 120

Config.CHAT_LIMIT_PER_MINUTE = 2
ratelimit.reset_all()
replies = [inbound(f"hola {i}").get("reply_text", "") for i in range(3)]
check("WhatsApp: más de 2 mensajes por minuto -> «Vas muy rápido»", "Vas muy rápido" in replies[2] and "Vas" not in replies[0], replies[2][:60])
Config.CHAT_LIMIT_PER_MINUTE = 20
Config.REMOTE_ALLOW_SYSTEM_TOOLS = False

# ======================= 4. Datos personales fuera de git =======================
tracked = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True).stdout.split()
check("data/memory, data/audio y data/learnings fuera del repositorio",
      not [f for f in tracked if f.startswith(("data/memory/", "data/audio/", "data/learnings/"))], tracked[:5])
ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
check("y en el .gitignore", all(x in ignored for x in ("data/memory/", "data/audio/", "data/learnings/")))

raise SystemExit(summary())
