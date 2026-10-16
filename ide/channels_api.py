"""Rutas de las Fases 9-11: WhatsApp, telefonía (Twilio), recordatorios y Heartbeat."""

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from agent.channels import notifier
from agent.channels import telephony, whatsapp
from agent.channels.security import check_bridge_secret, canonical_number
from agent.config import Config
from agent.paths import DATA_DIR, LOGS_DIR
from agent.heartbeat import Heartbeat
from agent.tools import reminder_tools

BASE_DIR = Path(__file__).resolve().parent.parent
BRIDGE_DIR = BASE_DIR / "bridges" / "whatsapp"
QR_FILE = DATA_DIR / "channels" / "whatsapp" / "qr.png"
BRIDGE_LOG = LOGS_DIR / "whatsapp-bridge.log"

router = APIRouter()
_state = {"provider": None, "heartbeat": None, "bridge": None}


class ReminderRequest(BaseModel):
    text: str
    when: str
    critical: bool = False
    repeat: str = "none"


# ---------------- ciclo de vida ----------------
def start_channels(provider, ui_broadcast, loop: asyncio.AbstractEventLoop, port: int = 8000):
    _state["provider"] = provider
    telephony.set_provider(provider)
    notifier.register_ui(ui_broadcast, loop)
    if Config.HEARTBEAT_ENABLED:
        hb = Heartbeat(provider, notifier)
        hb.start()
        _state["heartbeat"] = hb
    if Config.WHATSAPP_ENABLED and Config.AUTHORIZED_PHONE_NUMBERS:
        _start_bridge(port)


def stop_channels():
    if _state["heartbeat"]:
        _state["heartbeat"].stop()
    proc = _state["bridge"]
    if proc and proc.poll() is None:
        proc.terminate()


def _start_bridge(port: int):
    """Arranca el bridge de WhatsApp como proceso hijo (sin ventana) si Node y sus módulos están."""
    node = shutil.which("node")
    if not node or not (BRIDGE_DIR / "node_modules").exists():
        print("[WhatsApp] bridge no iniciado: instala Node 20+ y ejecuta 'npm install' en bridges/whatsapp")
        return
    BRIDGE_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(BRIDGE_LOG, "a", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    env = {**__import__("os").environ, "EDITH_URL": f"http://127.0.0.1:{port}", "EDITH_DATA_DIR": str(DATA_DIR)}
    _state["bridge"] = subprocess.Popen([node, "bridge.mjs"], cwd=str(BRIDGE_DIR), stdout=log, stderr=log,
                                        creationflags=flags, env=env)
    print(f"[WhatsApp] bridge iniciado (log: {BRIDGE_LOG})")


# ---------------- WhatsApp (Fase 9) ----------------
def _require_bridge(secret: Optional[str]):
    if not check_bridge_secret(secret):
        raise HTTPException(status_code=401, detail="unauthorized")


@router.get("/api/channels/whatsapp/allowlist")
def whatsapp_allowlist(x_edith_bridge_secret: Optional[str] = Header(None)):
    _require_bridge(x_edith_bridge_secret)
    return {"enabled": Config.WHATSAPP_ENABLED,
            "numbers": [canonical_number(n) for n in Config.AUTHORIZED_PHONE_NUMBERS]}


@router.post("/api/channels/whatsapp/inbound")
async def whatsapp_inbound(request: Request, x_edith_bridge_secret: Optional[str] = Header(None)):
    _require_bridge(x_edith_bridge_secret)
    payload = await request.json()
    return await whatsapp.handle_inbound(_state["provider"], payload)


@router.get("/api/channels/whatsapp/qr")
def whatsapp_qr():
    if not QR_FILE.exists():
        raise HTTPException(status_code=404, detail="No hay QR pendiente (ya vinculado o bridge apagado)")
    return FileResponse(QR_FILE, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/api/channels/status")
def channels_status():
    hb = _state["heartbeat"]
    return {
        "authorized_numbers": len(Config.AUTHORIZED_PHONE_NUMBERS),
        "owner": ("…" + Config.OWNER_PHONE_NUMBER[-4:]) if Config.OWNER_PHONE_NUMBER else None,
        "remote_system_tools": Config.REMOTE_ALLOW_SYSTEM_TOOLS,
        "whatsapp": {"enabled": Config.WHATSAPP_ENABLED,
                     **(whatsapp.bridge_status() if Config.WHATSAPP_ENABLED else {}),
                     "qr_available": QR_FILE.exists(),
                     "voice_replies": Config.WHATSAPP_VOICE_REPLIES},
        "phone": {"configured": telephony.configured(), "mode": Config.TWILIO_VOICE_MODE,
                  "public_url": bool(Config.PUBLIC_BASE_URL)},
        "heartbeat": hb.status() if hb else {"enabled": Config.HEARTBEAT_ENABLED, "running": False},
        "notifications": notifier.history[-10:],
    }


# ---------------- Teléfono (Fase 10) ----------------
async def _twilio_form(request: Request) -> dict:
    form = await request.form()
    params = {k: str(v) for k, v in form.items()}
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if not telephony.validate_twilio(path, params, request.headers.get("X-Twilio-Signature")):
        raise HTTPException(status_code=403, detail="Firma de Twilio inválida")
    return params


def _xml(twiml: str) -> Response:
    return Response(content=twiml, media_type="application/xml")


@router.post("/api/voice/incoming")
async def voice_incoming(request: Request):
    params = await _twilio_form(request)
    return _xml(telephony.incoming_twiml(params.get("From", "")))


@router.post("/api/voice/gather")
async def voice_gather(request: Request, t: str = Query("")):
    params = await _twilio_form(request)
    twiml = await asyncio.to_thread(telephony.gather_twiml, t, params.get("SpeechResult", ""))
    return _xml(twiml)


@router.post("/api/voice/result")
async def voice_result(request: Request, t: str = Query(""), n: int = Query(0)):
    await _twilio_form(request)
    return _xml(await asyncio.to_thread(telephony.result_twiml, t, n))


@router.post("/api/voice/alarm-ack")
async def voice_alarm_ack(request: Request, r: str = Query(""), t: str = Query("")):
    params = await _twilio_form(request)
    return _xml(telephony.alarm_ack_twiml(r, t, params.get("Digits", "")))


@router.websocket("/ws/voice")
async def voice_relay(websocket: WebSocket, t: str = Query("")):
    await telephony.relay_session(websocket, t)


# ---------------- Recordatorios y Heartbeat (Fase 11) ----------------
@router.get("/api/reminders")
def reminders_list():
    return reminder_tools.list_reminders()


@router.post("/api/reminders")
def reminders_create(req: ReminderRequest):
    res = reminder_tools.create_reminder(req.text, req.when, req.critical, req.repeat)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res


@router.delete("/api/reminders/{reminder_id}")
def reminders_cancel(reminder_id: str):
    res = reminder_tools.cancel_reminder(reminder_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/api/reminders/{reminder_id}/ack")
def reminders_ack(reminder_id: str):
    res = reminder_tools.ack_reminder(reminder_id)
    if not res:
        raise HTTPException(status_code=404, detail="No hay una alarma esperando confirmación con ese id")
    return res


@router.post("/api/heartbeat/run")
async def heartbeat_run(briefing: bool = Query(False)):
    hb = _state["heartbeat"] or Heartbeat(_state["provider"], notifier)
    return await asyncio.to_thread(hb.tick, None, True, briefing)
