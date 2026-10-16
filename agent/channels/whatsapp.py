"""Canal WhatsApp (Fase 9): EDITH <-> bridge local de Baileys (bridges/whatsapp).

Flujo entrante:  WhatsApp -> bridge -> POST /api/channels/whatsapp/inbound (con clave) -> aquí.
Flujo saliente:  notificaciones -> send_whatsapp() -> POST {bridge}/send (con clave) -> WhatsApp.
"""

import base64
import re
import unicodedata
from typing import Any, Dict, Optional

import httpx

from ..config import Config
from ..tools.reminder_tools import ack_reminder
from .conversations import get_channel_agent, reset_channel_agent
from .security import canonical_number, get_bridge_secret, is_authorized

# Solo palabras inequívocas: un "sí" suelto podría ser respuesta a otra pregunta de EDITH
ACK_WORDS = {"ok", "okay", "listo", "hecho", "confirmado", "confirmo", "entendido", "enterado", "👍", "✅"}
NEW_CHAT_WORDS = {"/nuevo", "/new", "/reset"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.strip().lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[.!¡¿?,\s]+$", "", t)


def to_whatsapp_markdown(text: str) -> str:
    """Markdown de EDITH -> formato de WhatsApp (*negrita*, _cursiva_, ```código```)."""
    t = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    t = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", t, flags=re.MULTILINE)
    t = re.sub(r"\$\$(.+?)\$\$", r"\1", t, flags=re.DOTALL)
    t = re.sub(r"(?<![\w$])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\d)", r"\1", t)
    t = re.sub(r"```[a-zA-Z0-9_+-]*\n", "```\n", t)
    return t.strip()


async def handle_inbound(provider, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Procesa un mensaje entrante del bridge y devuelve qué contestar."""
    import asyncio
    from .voice_notes import synthesize_voice_note, transcribe

    sender = canonical_number(payload.get("from", ""))
    if not Config.WHATSAPP_ENABLED:
        return {"ignore": True, "reason": "whatsapp_disabled"}
    if not is_authorized(sender):
        # Sin respuesta: no confirmar a desconocidos que aquí hay un asistente
        print(f"[WhatsApp] mensaje ignorado de número no autorizado …{sender[-4:]}")
        return {"ignore": True, "reason": "unauthorized"}

    text = (payload.get("text") or "").strip()
    was_voice = False
    if payload.get("audio_b64"):
        was_voice = True
        try:
            audio = base64.b64decode(payload["audio_b64"])
            text = await asyncio.to_thread(transcribe, audio)
        except Exception as e:
            return {"reply_text": f"No pude escuchar tu nota de voz ({type(e).__name__}). ¿Me lo escribes?"}
        if not text:
            return {"reply_text": "No entendí la nota de voz, ¿me la repites?"}

    if not text:
        return {"ignore": True, "reason": "empty"}

    norm = _norm(text)
    if norm in NEW_CHAT_WORDS:
        reset_channel_agent("whatsapp", sender)
        return {"reply_text": "🆕 Listo, empezamos una conversación nueva."}

    # "ok"/"listo" confirma una alarma crítica pendiente (evita que EDITH escale a llamada)
    if norm in ACK_WORDS:
        acked = ack_reminder()
        if acked:
            return {"reply_text": f"✅ Confirmado: _{acked['text']}_"}

    agent = get_channel_agent(provider, "whatsapp", sender)
    result = await asyncio.to_thread(agent.run, text)
    answer = result.answer or "…"
    reply: Dict[str, Any] = {"reply_text": to_whatsapp_markdown(answer)}
    if was_voice:
        reply["transcript"] = text

    mode = Config.WHATSAPP_VOICE_REPLIES
    if mode == "always" or (mode == "auto" and was_voice):
        try:
            note = await synthesize_voice_note(answer)
            if note:
                reply["reply_audio_b64"] = base64.b64encode(note).decode("ascii")
        except Exception as e:
            print(f"[WhatsApp] no se pudo generar la nota de voz: {e}")
    return reply


def bridge_status() -> Dict[str, Any]:
    try:
        r = httpx.get(f"{Config.WHATSAPP_BRIDGE_URL}/status", timeout=2.0,
                      headers={"X-Edith-Bridge-Secret": get_bridge_secret()})
        return r.json() if r.status_code == 200 else {"connected": False, "error": f"HTTP {r.status_code}"}
    except Exception:
        return {"connected": False, "error": "bridge apagado"}


def send_whatsapp(text: str = "", audio_ogg: Optional[bytes] = None, to: Optional[str] = None) -> bool:
    """Envía un mensaje proactivo (alertas, resumen matutino) al dueño o a un número autorizado."""
    to = canonical_number(to or Config.OWNER_PHONE_NUMBER)
    if not (Config.WHATSAPP_ENABLED and to and is_authorized(to)):
        return False
    body: Dict[str, Any] = {"to": to, "text": to_whatsapp_markdown(text) if text else ""}
    if audio_ogg:
        body["audio_b64"] = base64.b64encode(audio_ogg).decode("ascii")
    try:
        r = httpx.post(f"{Config.WHATSAPP_BRIDGE_URL}/send", json=body, timeout=30.0,
                       headers={"X-Edith-Bridge-Secret": get_bridge_secret()})
        return r.status_code == 200
    except Exception as e:
        print(f"[WhatsApp] no se pudo enviar: {e}")
        return False
