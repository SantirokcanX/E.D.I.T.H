"""Telefonía (Fase 10): llamar a EDITH y que EDITH te llame, vía Twilio Voice.

Dos modos para las llamadas entrantes (TWILIO_VOICE_MODE):
  * gather: por turnos. Twilio reconoce tu voz (<Gather input="speech">) y lee la respuesta
            (<Say>). Funciona con cualquier cuenta de Twilio desde el primer día.
  * relay:  tiempo real con ConversationRelay (Twilio hace voz<->texto por WebSocket y EDITH
            transmite la respuesta token a token). Requiere activar ConversationRelay en la
            consola de Twilio y una URL pública con TLS (wss://).

Seguridad: todos los webhooks verifican la firma X-Twilio-Signature; solo se atiende a números
autorizados; el WebSocket y las acciones de cada llamada exigen un token de un solo uso.
"""

import asyncio
import json
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Dict, Optional
from urllib.parse import urlencode

from ..config import Config
from ..tools.reminder_tools import ack_reminder
from .conversations import get_channel_agent
from .security import call_tokens, e164, is_authorized

ANSWER_WAIT_SECONDS = 9  # Twilio corta un webhook a los 15 s
MAX_WAIT_ROUNDS = 6
GOODBYE = re.compile(r"\b(adi[oó]s|hasta luego|nos vemos|cuelga|eso es todo|nada m[aá]s|bye)\b", re.IGNORECASE)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="edith-phone")
_pending: Dict[str, Dict] = {}
_pending_lock = threading.Lock()


def configured() -> bool:
    return bool(Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN and Config.TWILIO_PHONE_NUMBER)


def public_url(path: str, **query) -> str:
    q = f"?{urlencode(query)}" if query else ""
    return f"{Config.PUBLIC_BASE_URL}{path}{q}"


def validate_twilio(request_path_with_query: str, params: Dict[str, str], signature: Optional[str]) -> bool:
    """Valida X-Twilio-Signature contra la URL PÚBLICA que Twilio llamó (no la local)."""
    if not (Config.TWILIO_AUTH_TOKEN and Config.PUBLIC_BASE_URL and signature):
        return False
    from twilio.request_validator import RequestValidator
    return RequestValidator(Config.TWILIO_AUTH_TOKEN).validate(
        f"{Config.PUBLIC_BASE_URL}{request_path_with_query}", params, signature)


def speakable(text: str) -> str:
    """Texto de EDITH -> frase para leer por teléfono."""
    from ..voice.voice_engine import get_voice_engine
    t = get_voice_engine().clean_text_for_speech(text or "")
    t = t.replace("Te dejo todos los detalles completos por escrito en el panel.",
                  "Si quieres, te mando el detalle por WhatsApp.")
    return t or "Listo."


def _say(node, text: str):
    node.say(text, voice=Config.TWILIO_SAY_VOICE or None, language=Config.TWILIO_LANGUAGE)


def _gather(resp, token: str, prompt: Optional[str] = None):
    from twilio.twiml.voice_response import Gather
    g = Gather(input="speech", language=Config.TWILIO_LANGUAGE, speech_timeout="auto",
               action=public_url("/api/voice/gather", t=token), method="POST")
    if prompt:
        _say(g, prompt)
    resp.append(g)
    _say(resp, "No te escuché. Llámame cuando quieras. Hasta luego.")
    resp.hangup()


# ---------------- llamadas entrantes ----------------
def incoming_twiml(caller: str) -> str:
    from twilio.twiml.voice_response import Connect, VoiceResponse
    resp = VoiceResponse()
    if not is_authorized(caller):
        resp.reject(reason="rejected")  # sin contestar: no se cobra ni se revela nada
        return str(resp)
    token = call_tokens.issue(caller)
    greeting = "Hola, soy EDITH. ¿En qué te ayudo?"
    if Config.TWILIO_VOICE_MODE == "relay":
        ws_url = public_url("/ws/voice", t=token).replace("https://", "wss://", 1)
        connect = Connect()
        kwargs = {"url": ws_url, "language": Config.TWILIO_LANGUAGE, "welcome_greeting": greeting}
        if Config.TWILIO_RELAY_VOICE:
            kwargs["voice"] = Config.TWILIO_RELAY_VOICE
        connect.conversation_relay(**kwargs)
        resp.append(connect)
    else:
        _gather(resp, token, greeting)
    return str(resp)


def _answer_async(caller: str, speech: str) -> Future:
    agent = get_channel_agent(_provider(), "phone", caller)
    return _executor.submit(lambda: agent.run(speech, think=False).answer)


_provider_ref = None


def set_provider(provider):
    global _provider_ref
    _provider_ref = provider


def _provider():
    if _provider_ref is None:
        from ..providers import get_provider
        set_provider(get_provider())
    return _provider_ref


def _respond_or_wait(token: str, rounds: int) -> str:
    from twilio.twiml.voice_response import VoiceResponse
    resp = VoiceResponse()
    with _pending_lock:
        job = _pending.get(token)
    if not job:
        _gather(resp, token, "¿Qué más necesitas?")
        return str(resp)
    try:
        answer = job["future"].result(timeout=ANSWER_WAIT_SECONDS)
    except TimeoutError:
        if rounds >= MAX_WAIT_ROUNDS:
            with _pending_lock:
                _pending.pop(token, None)
            _gather(resp, token, "Me está tomando demasiado tiempo. Te lo envío por WhatsApp. ¿Algo más?")
            return str(resp)
        _say(resp, "Dame un momento.")
        resp.pause(length=1)
        resp.redirect(public_url("/api/voice/result", t=token, n=rounds + 1), method="POST")
        return str(resp)
    except Exception:
        answer = "Tuve un problema para responder eso."
    with _pending_lock:
        _pending.pop(token, None)
    if job.get("goodbye"):
        _say(resp, speakable(answer) + " Hasta luego.")
        resp.hangup()
        return str(resp)
    _gather(resp, token, speakable(answer))
    return str(resp)


def gather_twiml(token: str, speech: str) -> str:
    """Turno de conversación en modo gather."""
    from twilio.twiml.voice_response import VoiceResponse
    caller = call_tokens.peek(token)
    resp = VoiceResponse()
    if not caller:
        _say(resp, "Esta llamada ya no es válida.")
        resp.hangup()
        return str(resp)
    speech = (speech or "").strip()
    if not speech:
        _gather(resp, token, "No te escuché bien, ¿me lo repites?")
        return str(resp)
    if GOODBYE.search(speech) and len(speech.split()) <= 6:
        _say(resp, "Hasta luego.")
        resp.hangup()
        return str(resp)
    with _pending_lock:
        _pending[token] = {"future": _answer_async(caller, speech), "goodbye": bool(GOODBYE.search(speech))}
    return _respond_or_wait(token, 0)


def result_twiml(token: str, rounds: int) -> str:
    return _respond_or_wait(token, rounds)


# ---------------- ConversationRelay (tiempo real) ----------------
_SPEECH_STRIP = re.compile(r"[*#`_~$>|]")


async def relay_session(websocket, token: Optional[str]):
    """Maneja una llamada en modo relay. El token se emitió en el webhook firmado."""
    caller = call_tokens.consume(token)
    if not caller:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    agent = get_channel_agent(_provider(), "phone", caller)
    loop = asyncio.get_running_loop()
    speaking = {"stop": False}

    def on_chunk(chunk: str):
        if speaking["stop"]:
            return
        clean = _SPEECH_STRIP.sub("", chunk)
        if clean:
            asyncio.run_coroutine_threadsafe(
                websocket.send_text(json.dumps({"type": "text", "token": clean, "last": False})), loop)

    from ..core.reasoning_agent import AgentCallbacks
    try:
        while True:
            event = json.loads(await websocket.receive_text())
            kind = event.get("type")
            if kind == "prompt":
                prompt = (event.get("voicePrompt") or "").strip()
                if not prompt:
                    continue
                speaking["stop"] = False
                await loop.run_in_executor(
                    _executor, lambda: agent.run(prompt, AgentCallbacks(on_content_chunk=on_chunk), think=False))
                await websocket.send_text(json.dumps({"type": "text", "token": "", "last": True}))
                if GOODBYE.search(prompt) and len(prompt.split()) <= 6:
                    await websocket.send_text(json.dumps({"type": "end"}))
            elif kind == "interrupt":
                speaking["stop"] = True  # el usuario habló encima: deja de enviar el resto
            elif kind == "error":
                print(f"[Teléfono] error de ConversationRelay: {event.get('description')}")
    except Exception:
        pass


# ---------------- llamadas salientes (alarmas) ----------------
def make_call(message: str, reminder_id: Optional[str] = None, to: Optional[str] = None) -> Dict:
    """EDITH te llama y lee el mensaje. Si es una alarma, puedes confirmarla pulsando 1."""
    if not configured():
        return {"error": "Twilio no está configurado (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_PHONE_NUMBER)."}
    to = to or Config.OWNER_PHONE_NUMBER
    if not is_authorized(to):
        return {"error": "Solo puedo llamar a números autorizados."}
    from twilio.rest import Client
    from twilio.twiml.voice_response import Gather, VoiceResponse
    resp = VoiceResponse()
    spoken = speakable(message)
    if Config.PUBLIC_BASE_URL and reminder_id:
        token = call_tokens.issue(to)
        g = Gather(num_digits=1, timeout=8, method="POST",
                   action=public_url("/api/voice/alarm-ack", r=reminder_id, t=token))
        _say(g, f"Hola, soy EDITH. {spoken} Presiona 1 para confirmar.")
        resp.append(g)
        _say(resp, "No recibí confirmación. Te lo dejo por WhatsApp.")
    else:
        _say(resp, f"Hola, soy EDITH. {spoken}")
        resp.pause(length=1)
        _say(resp, f"Repito: {spoken}")
    try:
        call = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN).calls.create(
            to=e164(to), from_=Config.TWILIO_PHONE_NUMBER, twiml=str(resp))
        return {"status": "llamando", "sid": call.sid}
    except Exception as e:
        return {"error": f"Twilio rechazó la llamada: {e}"}


def alarm_ack_twiml(reminder_id: str, token: str, digits: str) -> str:
    from twilio.twiml.voice_response import VoiceResponse
    resp = VoiceResponse()
    if call_tokens.consume(token) and digits == "1" and ack_reminder(reminder_id):
        _say(resp, "Confirmado. Gracias.")
    else:
        _say(resp, "No pude confirmar la alarma. Te la recuerdo por WhatsApp.")
    resp.hangup()
    return str(resp)
