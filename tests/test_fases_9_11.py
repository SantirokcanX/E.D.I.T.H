"""Pruebas funcionales de las Fases 9, 10 y 11 (modelo simulado, datos en carpetas temporales).

Uso:  python tests/test_fases_9_11.py   (desde la raíz del proyecto, con el .venv activado)
"""
import asyncio, base64, io, json, sys, threading, time
from datetime import datetime, timedelta
from pathlib import Path

from entorno import TMP, VAULT, Config, FakeProvider as Fake, check, dm, mm, rt, sec, summary

# ======================= FASE 11: recordatorios =======================
now = datetime.now()
r1 = rt.create_reminder("Tomar agua", "+1m")
check("crear recordatorio relativo (+1m)", r1.get("result") == "creado" and r1.get("status") == "pending", r1.get("due"))
r_bad = rt.create_reminder("x", "ayer por la tarde")
check("fecha no reconocida devuelve error claro", "error" in r_bad)
r_past = rt.create_reminder("x", (now - timedelta(hours=2)).isoformat(timespec="minutes"))
check("fecha pasada rechazada", "error" in r_past)
r2 = rt.create_reminder("Presentación 8:30", (now + timedelta(minutes=2)).isoformat(timespec="minutes"), critical=True)
r3 = rt.create_reminder("Vitaminas", (now + timedelta(minutes=3)).isoformat(timespec="minutes"), repeat="daily")
fired = rt.take_due(now + timedelta(minutes=5))
check("take_due dispara los 3 que ya tocan", len(fired) == 3, [f["text"] for f in fired])
active = rt.list_reminders()
check("el diario se reprograma para mañana", any(a["text"] == "Vitaminas" and a["status"] == "pending" for a in active))
check("el crítico queda esperando confirmación", any(a["text"].startswith("Presentación") and a["status"] == "fired" for a in active))
esc_early = rt.awaiting_escalation(10, now + timedelta(minutes=8))
esc = rt.awaiting_escalation(10, now + timedelta(minutes=20))
check("escala solo tras ESCALATE_AFTER_MINUTES", not esc_early and len(esc) == 1)
check("no escala dos veces", not rt.awaiting_escalation(10, now + timedelta(minutes=40)))
ack = rt.ack_reminder()
check("confirmar alarma crítica", ack and ack["text"].startswith("Presentación"))

# ======================= servidor =======================
import ide.server as srv
from fastapi.testclient import TestClient
import ide.channels_api as capi
from agent.channels import telephony, notifier as notifier_mod
fake = Fake()
capi._state["provider"] = fake
telephony.set_provider(fake)
captured = []
async def fake_broadcast(ev): captured.append(ev)
client = TestClient(srv.app, base_url="http://127.0.0.1:8000")
# Fase 14: las rutas de la interfaz piden el token (las del bridge y Twilio, no)
UI = {"Authorization": f"Bearer {sec.get_api_token()}"}
loop = asyncio.new_event_loop()
threading.Thread(target=loop.run_forever, daemon=True).start()
notifier_mod.register_ui(fake_broadcast, loop)

# ======================= FASE 9: WhatsApp =======================
secret = sec.get_bridge_secret()
check("clave del bridge generada (>=32 caracteres)", len(secret) >= 32 and sec.BRIDGE_SECRET_FILE.exists())
r = client.post("/api/channels/whatsapp/inbound", json={"from": "5215512345678", "text": "hola"})
check("inbound sin clave -> 401", r.status_code == 401)
r = client.post("/api/channels/whatsapp/inbound", json={"from": "5215512345678", "text": "hola"},
                headers={"X-Edith-Bridge-Secret": "x" * 43})
check("inbound con clave incorrecta -> 401", r.status_code == 401)
H = {"X-Edith-Bridge-Secret": secret}
r = client.post("/api/channels/whatsapp/inbound", json={"from": "5215512345678", "text": "hola"}, headers=H)
check("WhatsApp desactivado -> ignora", r.json().get("ignore") is True)

Config.WHATSAPP_ENABLED = True
Config.AUTHORIZED_PHONE_NUMBERS = ["525512345678"]  # sin el 1: debe aceptar también 521…
Config.OWNER_PHONE_NUMBER = "525512345678"
r = client.get("/api/channels/whatsapp/allowlist", headers=H)
check("allowlist para el bridge", r.json() == {"enabled": True, "numbers": ["525512345678"]}, r.json())
r = client.post("/api/channels/whatsapp/inbound", json={"from": "5215599999999", "text": "hola"}, headers=H)
check("número no autorizado -> silencio", r.json().get("ignore") is True and r.json().get("reason") == "unauthorized")
r = client.post("/api/channels/whatsapp/inbound", json={"from": "5215512345678", "text": "hola EDITH"}, headers=H)
j = r.json()
check("autorizado (forma 521 = 52) recibe respuesta", "reply_text" in j, j.get("reply_text"))
check("formato WhatsApp: **x** -> *x* y sin $", "*Todo bien*" in j.get("reply_text", "") and "$" not in j.get("reply_text", ""))
check("respuesta de texto sin nota de voz (modo auto)", "reply_audio_b64" not in j)
check("WhatsApp no ofrece herramientas locales al modelo",
      "run_system_command" not in Fake.seen_tools and "create_reminder" in Fake.seen_tools)
r = client.post("/api/channels/whatsapp/inbound", json={"from": "525512345678", "text": "ejecuta en powershell dir"}, headers=H)
check("PowerShell bloqueado desde WhatsApp", "desactivada en este canal" in r.json().get("reply_text", ""), r.json().get("reply_text", "")[:90])
sessions = [s["id"] for s in mm._global_memory_manager.list_sessions()]
check("la charla de WhatsApp aparece en el historial con su prefijo", any(s.startswith("whatsapp_525512345678_") for s in sessions), sessions)
r = client.post("/api/channels/whatsapp/inbound", json={"from": "525512345678", "text": "/nuevo"}, headers=H)
check("/nuevo reinicia la conversación", "nueva" in r.json().get("reply_text", "").lower())

# alarma crítica confirmada con "ok" por WhatsApp
rt.create_reminder("Llamar al banco", "+1m", critical=True)
rt.take_due(datetime.now() + timedelta(minutes=2))
r = client.post("/api/channels/whatsapp/inbound", json={"from": "525512345678", "text": "Ok!"}, headers=H)
check("'Ok!' confirma la alarma crítica", "Confirmado" in r.json().get("reply_text", ""), r.json().get("reply_text"))

# nota de voz real: SAPI5 -> ogg/opus -> faster-whisper -> respuesta con nota de voz
from agent.voice.voice_engine import VoiceEngine
from agent.channels.voice_notes import to_ogg_opus
Config.WHISPER_MODEL = "base"  # más ligero para la prueba
wav = VoiceEngine.synthesize_offline("Hola EDITH, recuérdame comprar leche mañana.", TMP / "in.wav")
check("voz de prueba generada (SAPI5)", bool(wav))
ogg = to_ogg_opus(Path(wav).read_bytes())
check("transcodificación a Ogg/Opus", ogg[:4] == b"OggS", f"{len(ogg)} bytes")
t0 = time.time()
r = client.post("/api/channels/whatsapp/inbound", json={"from": "525512345678",
                "audio_b64": base64.b64encode(ogg).decode(), "audio_mime": "audio/ogg"}, headers=H)
j = r.json()
check("nota de voz transcrita", "leche" in j.get("transcript", "").lower(), f"'{j.get('transcript')}' en {time.time()-t0:.1f}s (incluye descarga del modelo)")
audio = base64.b64decode(j.get("reply_audio_b64", "")) if j.get("reply_audio_b64") else b""
import av
codec = None
if audio:
    with av.open(io.BytesIO(audio)) as c:
        codec = c.streams.audio[0].codec_context.name, c.streams.audio[0].channels
check("responde con nota de voz Ogg/Opus mono", audio[:4] == b"OggS" and codec == ("opus", 1), codec)

# ======================= FASE 10: teléfono =======================
from twilio.request_validator import RequestValidator
Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN, Config.TWILIO_PHONE_NUMBER = "AC" + "0" * 32, "test-token", "+15550001111"
Config.PUBLIC_BASE_URL = "https://edith.example"
val = RequestValidator(Config.TWILIO_AUTH_TOKEN)
def twilio_post(path, params):
    sig = val.compute_signature(Config.PUBLIC_BASE_URL + path, params)
    return client.post(path, data=params, headers={"X-Twilio-Signature": sig})

r = client.post("/api/voice/incoming", data={"From": "+525512345678"}, headers={"X-Twilio-Signature": "falsa"})
check("webhook con firma falsa -> 403", r.status_code == 403)
r = twilio_post("/api/voice/incoming", {"From": "+525599999999", "CallSid": "CA1"})
check("llamada de número desconocido -> <Reject>", "<Reject" in r.text, r.text[:120])
Config.TWILIO_VOICE_MODE = "gather"
r = twilio_post("/api/voice/incoming", {"From": "+5215512345678", "CallSid": "CA2"})
check("llamada autorizada (modo gather) -> <Gather> en español", "<Gather" in r.text and 'language="es-MX"' in r.text)
import re as _re
token = _re.search(r"t=([\w-]+)", r.text).group(1)
r = twilio_post(f"/api/voice/gather?t={token}", {"SpeechResult": "¿Cómo estás?", "CallSid": "CA2"})
check("turno de voz: EDITH responde con <Say> y vuelve a escuchar", "<Say" in r.text and "Todo bien" in r.text and "<Gather" in r.text)
check("lo hablado no lleva Markdown ni LaTeX", "**" not in r.text and "$" not in r.text)
telephony.ANSWER_WAIT_SECONDS = 1
Fake.delay = 2.5
r = twilio_post(f"/api/voice/gather?t={token}", {"SpeechResult": "Explícame algo largo", "CallSid": "CA2"})
check("respuesta lenta: 'Dame un momento' + <Redirect>", "<Redirect" in r.text and "momento" in r.text)
time.sleep(2)
r = twilio_post(f"/api/voice/result?t={token}&n=1", {"CallSid": "CA2"})
check("tras esperar, llega la respuesta", "Todo bien" in r.text)
Fake.delay = 0
r = twilio_post("/api/voice/gather?t=token-inventado", {"SpeechResult": "hola"})
check("token de llamada inventado -> se cuelga", "<Hangup" in r.text)
r = twilio_post(f"/api/voice/gather?t={token}", {"SpeechResult": "adiós"})
check("'adiós' cuelga la llamada", "<Hangup" in r.text)

Config.TWILIO_VOICE_MODE = "relay"
r = twilio_post("/api/voice/incoming", {"From": "+525512345678", "CallSid": "CA3"})
check("modo relay -> <ConversationRelay> con wss://", "<ConversationRelay" in r.text and "wss://edith.example/ws/voice" in r.text)
rtoken = _re.search(r"t=([\w-]+)", r.text).group(1)
with client.websocket_connect(f"ws://127.0.0.1:8000/ws/voice?t={rtoken}") as ws:
    ws.send_text(json.dumps({"type": "setup", "callSid": "CA3"}))
    ws.send_text(json.dumps({"type": "prompt", "voicePrompt": "hola", "last": True}))
    tokens = []
    while True:
        m = json.loads(ws.receive_text())
        tokens.append(m)
        if m.get("last"):
            break
spoken = "".join(m["token"] for m in tokens)
check("relay transmite la respuesta token a token", len(tokens) > 3 and "Todo bien" in spoken and "*" not in spoken, spoken[:60])
try:
    with client.websocket_connect(f"ws://127.0.0.1:8000/ws/voice?t={rtoken}") as ws:
        ws.receive_text()
    reused = True
except Exception:
    reused = False
check("el token del WebSocket es de un solo uso", not reused)

# llamada saliente de alarma (sin llamar de verdad: se captura lo que se enviaría a Twilio)
import twilio.rest
sent_calls = []
class FakeCalls:
    def create(self, **kw): sent_calls.append(kw); return type("C", (), {"sid": "CA_fake"})()
class FakeClient:
    def __init__(self, *a): self.calls = FakeCalls()
orig_client = twilio.rest.Client
twilio.rest.Client = FakeClient
res = telephony.make_call("Recordatorio urgente: presentación a las 8:30", reminder_id="abc123")
twilio.rest.Client = orig_client
tw = sent_calls[0]["twiml"] if sent_calls else ""
check("llamada de alarma al dueño en E.164 con 'presiona 1'", res.get("sid") == "CA_fake" and sent_calls[0]["to"] == "+525512345678" and "Presiona 1" in tw)
rt.create_reminder("Presentación", "+1m", critical=True)
fired = rt.take_due(datetime.now() + timedelta(minutes=2))
rid = fired[0]["id"]
atoken = sec.call_tokens.issue("525512345678")
r = twilio_post(f"/api/voice/alarm-ack?r={rid}&t={atoken}", {"Digits": "1"})
check("pulsar 1 en la llamada confirma la alarma", "Confirmado" in r.text and not any(x["id"] == rid and x["status"] == "fired" for x in rt.list_reminders()))
Config.AUTHORIZED_PHONE_NUMBERS = []
check("sin números autorizados no llama a nadie", "error" in telephony.make_call("x", to="+525512345678"))
Config.AUTHORIZED_PHONE_NUMBERS = ["525512345678"]

# ======================= FASE 11: Heartbeat =======================
(VAULT / "02 - Proyectos").mkdir()
today = datetime.now().date().isoformat()
yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
(VAULT / "02 - Proyectos" / "Tareas.md").write_text(
    f"- [ ] Entregar informe 📅 {today}\n- [ ] Pagar luz due:: {yesterday}\n- [x] Hecha 📅 {today}\n- [ ] Sin fecha\n", encoding="utf-8")
from agent.heartbeat import Heartbeat
from agent.channels.notifier import notifier as N, in_quiet_hours
Config.NOTIFY_CHANNELS = ["ui"]
Config.QUIET_HOURS = "23:00-07:00"
hb = Heartbeat(fake, N)
rt.create_reminder("Estirar la espalda", "+1m")
captured.clear()
rep = hb.tick(now=datetime.now() + timedelta(minutes=2), force_full=True)
time.sleep(0.3)
check("heartbeat dispara el recordatorio y avisa a la interfaz",
      "Estirar la espalda" in rep["reminders"] and any(e["message"] == "Estirar la espalda" for e in captured), rep["reminders"])
check("lee tareas de Obsidian con fecha (hoy y vencidas)",
      any("Entregar informe" in t for t in rep["tasks"]["today"]) and any("Pagar luz" in t for t in rep["tasks"]["overdue"])
      and not any("Hecha" in t or "Sin fecha" in t for t in rep["tasks"]["today"] + rep["tasks"]["overdue"]), rep["tasks"])
check("revisa salud de la laptop", "cpu" in rep["system"], rep["system"])
b = hb.morning_briefing()
check("resumen matutino redactado por el modelo", b["text"].startswith("Buenos días"), b["text"])
check("resumen guardado en Obsidian (01 - Diario)", b["note"] and (VAULT / b["note"]).exists(), b["note"])
check("en español", b["facts"]["fecha"].split()[0] in dm.DIAS, b["facts"]["fecha"])
Config.MORNING_BRIEFING_TIME = "08:00"
hb.state.pop("last_briefing_date", None)
check("resumen a las 08:30 sí", hb._briefing_due(datetime.now().replace(hour=8, minute=30)))
hb.state.pop("last_briefing_date", None)
check("resumen a las 16:00 no (llegó tarde)", not hb._briefing_due(datetime.now().replace(hour=16, minute=0)))
check("horas de silencio 23:00-07:00", in_quiet_hours(datetime.now().replace(hour=2)) and not in_quiet_hours(datetime.now().replace(hour=12)))
r = client.post("/api/reminders", json={"text": "Desde la interfaz", "when": "+2h", "critical": False}, headers=UI)
check("API: crear recordatorio", r.status_code == 200 and r.json()["text"] == "Desde la interfaz")
check("API: estado de canales", client.get("/api/channels/status", headers=UI).status_code == 200)

# ======================= Arreglo del workspace =======================
from agent.tools.workspace_tools import get_workspace_path
try:
    get_workspace_path("../workspace_x/archivo.txt"); blocked = False
except ValueError:
    blocked = True
check("workspace: '../workspace_x/…' ahora se bloquea", blocked)
check("workspace: rutas normales siguen funcionando", get_workspace_path("notas/a.md").name == "a.md")

sys.exit(summary())
