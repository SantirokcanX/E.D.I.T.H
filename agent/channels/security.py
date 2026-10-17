"""Controles de acceso: canales remotos (WhatsApp y teléfono) y token de la interfaz (Fase 14).

Principio: falla cerrado. Si no hay números autorizados o falta la clave, nadie entra.
"""

import hmac
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .. import secret_store
from ..config import Config

from ..paths import DATA_DIR

CHANNELS_DIR = DATA_DIR / "channels"
BRIDGE_SECRET_FILE = CHANNELS_DIR / "bridge_secret"
API_TOKEN_FILE = CHANNELS_DIR / "api_token"
_secret_lock = threading.Lock()


def digits(number: str) -> str:
    return "".join(ch for ch in (number or "") if ch.isdigit())


def canonical_number(number: str) -> str:
    """Forma comparable de un teléfono. México y Argentina tienen dos formas para el mismo
    celular (WhatsApp/Twilio pueden usar 521… o 52…, 549… o 54…): se unifican."""
    d = digits(number)
    if len(d) == 13 and d.startswith("521"):
        return "52" + d[3:]
    if len(d) == 13 and d.startswith("549"):
        return "54" + d[3:]
    return d


def is_authorized(number: str) -> bool:
    n = canonical_number(number)
    return bool(n) and any(n == canonical_number(a) for a in Config.AUTHORIZED_PHONE_NUMBERS)


def e164(number: str) -> str:
    d = canonical_number(number)
    return f"+{d}" if d else ""


def _local_secret(env_name: str, path: Path) -> str:
    """Secreto de la variable de entorno o, si no está, del archivo (se genera la primera vez).
    En disco va cifrado con DPAPI; un archivo antiguo en texto plano se cifra al leerlo."""
    env = os.getenv(env_name, "").strip()
    if env:
        return env
    with _secret_lock:  # dos peticiones a la vez no deben generar dos secretos distintos
        try:
            stored = path.read_text(encoding="utf-8").strip()
            value = secret_store.unprotect(stored)
            if len(value) >= 32:
                if not secret_store.is_protected(stored) and secret_store.available():
                    path.write_text(secret_store.protect(value), encoding="utf-8")
                return value
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(32)
        path.write_text(secret_store.protect(value), encoding="utf-8")
        return value


def get_bridge_secret() -> str:
    """Clave compartida EDITH <-> bridge de WhatsApp. Se genera sola la primera vez
    (data/channels/bridge_secret, cifrada) y EDITH se la pasa al bridge en EDITH_BRIDGE_SECRET."""
    return _local_secret("EDITH_BRIDGE_SECRET", BRIDGE_SECRET_FILE)


def get_api_token() -> str:
    """Token de acceso a la interfaz, la API y el WebSocket del chat (EDITH_API_TOKEN o
    data/channels/api_token en la carpeta de datos, que se genera solo la primera vez)."""
    return _local_secret("EDITH_API_TOKEN", API_TOKEN_FILE)


def check_bridge_secret(provided: Optional[str]) -> bool:
    return bool(provided) and hmac.compare_digest(provided, get_bridge_secret())


class CallTokens:
    """Tokens de un solo uso por llamada: el webhook de Twilio (firmado) emite uno y el
    WebSocket / las acciones de esa llamada solo se aceptan si lo presentan."""

    TTL_SECONDS = 3600

    def __init__(self):
        self._tokens: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, caller: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._purge()
            self._tokens[token] = (caller, time.time() + self.TTL_SECONDS)
        return token

    def peek(self, token: Optional[str]) -> Optional[str]:
        with self._lock:
            self._purge()
            item = self._tokens.get(token or "")
            return item[0] if item else None

    def consume(self, token: Optional[str]) -> Optional[str]:
        with self._lock:
            self._purge()
            item = self._tokens.pop(token or "", None)
            return item[0] if item else None

    def _purge(self):
        now = time.time()
        for k in [k for k, (_, exp) in self._tokens.items() if exp < now]:
            del self._tokens[k]


call_tokens = CallTokens()
