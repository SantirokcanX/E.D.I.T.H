"""Canal WhatsApp (Fase 9): EDITH <-> bridge local de Baileys (bridges/whatsapp).

Flujo entrante:  WhatsApp -> bridge -> POST /api/channels/whatsapp/inbound (con clave) -> aquí.
Flujo saliente:  notificaciones -> send_whatsapp() -> POST {bridge}/send (con clave) -> WhatsApp.
"""

import base64
import json
import re
import secrets
import threading
import unicodedata
from typing import Any, Callable, Dict, Optional, Tuple

import httpx

from .. import ratelimit
from ..config import Config
from ..tools.reminder_tools import ack_reminder
from .conversations import get_channel_agent, reset_channel_agent
from .security import canonical_number, get_bridge_secret, is_authorized

# Solo palabras inequívocas: un "sí" suelto podría ser respuesta a otra pregunta de EDITH
ACK_WORDS = {"ok", "okay", "listo", "hecho", "confirmado", "confirmo", "entendido", "enterado", "👍", "✅"}
NEW_CHAT_WORDS = {"/nuevo", "/new", "/reset"}

# Confirmación por WhatsApp (Fase 14): una acción sensible pedida desde el celular espera a que
# respondas "SI <código>". El código evita que un "sí" a otra pregunta autorice por accidente.
CONFIRM_TIMEOUT = 120
YES_WORDS = {"si", "autorizo", "autorizado", "dale", "adelante", "hazlo"}
NO_WORDS = {"no", "cancela", "cancelar", "cancelalo", "rechazo", "nel", "alto", "detente"}
_pending: Dict[str, Dict[str, Any]] = {}  # número -> {"code", "event", "approved"}
_pending_lock = threading.Lock()


def _describe_action(tool_name: str, args: Dict[str, Any]) -> Tuple[str, str]:
    if tool_name == "run_system_command":
        return "ejecutar en PowerShell", str(args.get("command", ""))
    if tool_name == "open_application":
        return "abrir una aplicación", str(args.get("app_name", ""))
    return f"usar «{tool_name}»", json.dumps(args, ensure_ascii=False)


def confirm_via_whatsapp(sender: str) -> Callable[[str, Dict[str, Any], str], bool]:
    """on_confirm del agente: pregunta por WhatsApp y espera "SI <código>" (o "NO") del mismo número."""
    def on_confirm(tool_name: str, args: Dict[str, Any], reason: str) -> bool:
        action, detail = _describe_action(tool_name, args)
        entry = {"code": f"{secrets.randbelow(9000) + 1000}", "event": threading.Event(), "approved": False}
        with _pending_lock:
            _pending[sender] = entry
        text = (f"🔐 *EDITH quiere {action} en la laptop:*\n```{detail[:400]}```\n"
                + (f"_{reason}_\n" if reason else "")
                + f"Responde *SI {entry['code']}* para autorizar o *NO* para cancelar (caduca en 2 min).")
        if not send_whatsapp(text=text, to=sender):
            with _pending_lock:
                _pending.pop(sender, None)
            return False
        answered = entry["event"].wait(CONFIRM_TIMEOUT)
        with _pending_lock:
            if _pending.get(sender) is entry:
                del _pending[sender]
        if not answered:
            send_whatsapp(text="⌛ No respondiste a tiempo: no lo hice.", to=sender)
        return answered and entry["approved"]
    return on_confirm


def _confirmation_answer(norm: str, code: str) -> Optional[bool]:
    """True = autoriza, False = rechaza, None = no es una respuesta válida a la confirmación."""
    words = re.findall(r"\w+", norm)  # "si, 4821" o "SÍ 4821!" -> ["si", "4821"]
    if words and words[0] in NO_WORDS:
        return False
    if code in words and all(w in YES_WORDS or w == code for w in words):
        return True
    return None


def answer_pending_confirmation(sender: str, norm: str) -> Optional[str]:
    """Si hay una autorización pendiente para este número, la resuelve y devuelve qué contestar."""
    with _pending_lock:
        entry = _pending.get(sender)
    if not entry:
        return None
    answer = _confirmation_answer(norm, entry["code"])
    if answer is None:
        return f"Antes dime si autorizas lo pendiente: responde *SI {entry['code']}* o *NO*."
    entry["approved"] = answer
    entry["event"].set()
    return "✅ Autorizado, lo hago." if answer else "❌ Cancelado, no lo hago."


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
    pending_reply = answer_pending_confirmation(sender, norm)
    if pending_reply:
        return {"reply_text": pending_reply}
    if norm in NEW_CHAT_WORDS:
        reset_channel_agent("whatsapp", sender)
        return {"reply_text": "🆕 Listo, empezamos una conversación nueva."}

    # "ok"/"listo" confirma una alarma crítica pendiente (evita que EDITH escale a llamada)
    if norm in ACK_WORDS:
        acked = ack_reminder()
        if acked:
            return {"reply_text": f"✅ Confirmado: _{acked['text']}_"}

    if not ratelimit.chat.hit("wa:" + sender):
        return {"reply_text": f"Vas muy rápido: máximo {Config.CHAT_LIMIT_PER_MINUTE} mensajes por minuto. "
                              "Espera un momento y me lo repites."}
    from ..core.reasoning_agent import AgentCallbacks
    agent = get_channel_agent(provider, "whatsapp", sender)
    result = await asyncio.to_thread(agent.run, text, AgentCallbacks(on_confirm=confirm_via_whatsapp(sender)))
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
