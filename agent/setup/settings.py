"""Ajustes de EDITH editables desde la app (Fase 15.2).

Un solo esquema alimenta el asistente de primer arranque y el panel de Ajustes. Los valores
se guardan en el MISMO .env que lee EDITH (el del proyecto en desarrollo o el de
%LOCALAPPDATA%\\EDITH en la app instalada): no hay dos fuentes de verdad. Casi todo se
aplica al momento; solo el puerto y el atajo global piden reiniciar.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import set_key

from .. import config as config_module
from .. import secret_store
from ..config import Config
from ..paths import EDITH_HOME, PROJECT_DIR

SETUP_FILE = EDITH_HOME / "setup.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
MASK = "••••••••"

VOICE_CHOICES = [("elvira", "Elvira (cálida, España)"), ("dalia", "Dalia (serena, México)"),
                 ("ximena", "Ximena (espontánea, España)"), ("salome", "Salomé (empática, Colombia)")]

# type: text | secret | bool | select | number | time | timerange | phones | phone | url | folder | multi | model | voice
SCHEMA: List[Dict[str, Any]] = [
    {"id": "perfil", "title": "Tú", "icon": "🙂", "fields": [
        {"key": "USER_NAME", "label": "¿Cómo te llamas?", "type": "text", "store": "profile",
         "help": "EDITH te llamará así y lo recordará en todas las conversaciones."},
    ]},
    {"id": "modelos", "title": "Modelos de IA", "icon": "🧠", "fields": [
        {"key": "OLLAMA_MODEL", "label": "Modelo rápido", "type": "model",
         "help": "Responde la charla normal y usa las herramientas. Debe caber entero en tu GPU."},
        {"key": "OLLAMA_DEEP_MODEL", "label": "Modelo para pensar a fondo", "type": "model", "allow_empty": True,
         "help": "Matemáticas, lógica y depuración. Vacío = usar el rápido para todo (sirve con modelos híbridos)."},
        {"key": "OLLAMA_THINK", "label": "Razonamiento", "type": "select",
         "options": [["auto", "Automático (recomendado)"], ["false", "Siempre rápido"], ["true", "Siempre a fondo"]]},
        {"key": "VISION_MODEL", "label": "Modelo de visión (fotos y pantalla)", "type": "model", "allow_empty": True,
         "help": "Ve fotos de WhatsApp y tu pantalla sin salir de la laptop. qwen3-vl:4b ocupa unos 3 GB. Vacío = sin visión local."},
    ]},
    {"id": "obsidian", "title": "Obsidian", "icon": "💎", "fields": [
        {"key": "OBSIDIAN_VAULT_PATH", "label": "Carpeta de tu bóveda", "type": "folder",
         "help": "EDITH guarda y lee notas aquí. Si la carpeta está vacía, crea la estructura 00-04."},
        {"key": "OBSIDIAN_AUTO_SYNC", "label": "Guardar cada conversación en el Diario", "type": "bool"},
        {"key": "OBSIDIAN_SAVE_WORKSPACE", "label": "Copiar a la bóveda los diagramas y las notas del día", "type": "bool",
         "help": "Diagramas en «03 - Conocimiento/Diagramas» (Obsidian dibuja Mermaid) y las notas del día en el Diario."},
    ]},
    {"id": "voz", "title": "Voz", "icon": "🔊", "fields": [
        {"key": "EDITH_VOICE", "label": "Voz de EDITH", "type": "voice", "options": VOICE_CHOICES},
        {"key": "VOICE_OFFLINE_FALLBACK", "label": "Usar la voz de Windows si no hay internet", "type": "bool"},
    ]},
    {"id": "canales", "title": "WhatsApp y teléfono", "icon": "📱", "fields": [
        {"key": "AUTHORIZED_PHONE_NUMBERS", "label": "Números autorizados", "type": "phones",
         "help": "Solo estos números pueden hablar con EDITH. Formato internacional: +5215512345678. Vacío = nadie."},
        {"key": "OWNER_PHONE_NUMBER", "label": "Número al que EDITH avisa", "type": "phone", "allow_empty": True,
         "help": "Vacío = el primero de la lista."},
        {"key": "WHATSAPP_ENABLED", "label": "Activar WhatsApp", "type": "bool",
         "help": "Vincula un número secundario: Baileys es un cliente no oficial de WhatsApp."},
        {"key": "WHATSAPP_VOICE_REPLIES", "label": "Responder con nota de voz", "type": "select",
         "options": [["auto", "Si yo mando nota de voz"], ["always", "Siempre"], ["never", "Nunca"]]},
        {"key": "WHISPER_MODEL", "label": "Precisión al transcribir notas de voz", "type": "select",
         "options": [["base", "Básica (rápida, 145 MB)"], ["small", "Buena (recomendada, 460 MB)"],
                     ["medium", "Alta (lenta, 1.5 GB)"]]},
        {"key": "TWILIO_ACCOUNT_SID", "label": "Twilio: Account SID", "type": "text", "allow_empty": True},
        {"key": "TWILIO_AUTH_TOKEN", "label": "Twilio: Auth Token", "type": "secret", "allow_empty": True},
        {"key": "TWILIO_PHONE_NUMBER", "label": "Twilio: número de EDITH", "type": "phone", "allow_empty": True},
        {"key": "PUBLIC_BASE_URL", "label": "URL pública HTTPS (Fase 8)", "type": "url", "allow_empty": True,
         "help": "Por donde Twilio llega a EDITH: Tailscale Funnel, Cloudflare Tunnel…"},
        {"key": "TWILIO_VOICE_MODE", "label": "Modo de las llamadas", "type": "select",
         "options": [["gather", "Por turnos (funciona siempre)"], ["relay", "Tiempo real (requiere ConversationRelay)"]]},
        {"key": "REMOTE_ALLOW_SYSTEM_TOOLS", "label": "Permitir PowerShell y apps desde WhatsApp/teléfono",
         "type": "bool", "danger": True,
         "help": "Cada comando o app te pide autorización por WhatsApp (respondes SI y un código; caduca en "
                 "2 min). Desde una llamada siempre se rechazan. Úsalo solo si tus números son de confianza."},
    ]},
    {"id": "autonomia", "title": "Autonomía", "icon": "⏰", "fields": [
        {"key": "HEARTBEAT_ENABLED", "label": "Avisos, recordatorios y vigilancia (Heartbeat)", "type": "bool"},
        {"key": "MORNING_BRIEFING_TIME", "label": "Hora del resumen matutino", "type": "time", "allow_empty": True,
         "help": "Vacío = sin resumen."},
        {"key": "QUIET_HOURS", "label": "Horas de silencio", "type": "timerange",
         "help": "De noche solo pasan los avisos críticos."},
        {"key": "HEARTBEAT_NEWS_TOPICS", "label": "Temas de noticias para el resumen", "type": "text", "allow_empty": True,
         "help": "Separados por comas, p. ej. inteligencia artificial, tecnología."},
        {"key": "NOTIFY_CHANNELS", "label": "Avisar por", "type": "multi",
         "options": [["ui", "Ventana de EDITH"], ["toast", "Notificaciones de Windows"], ["whatsapp", "WhatsApp"]]},
        {"key": "ESCALATE_AFTER_MINUTES", "label": "Minutos antes de llamarte por una alarma sin confirmar",
         "type": "number", "min": 1, "max": 240},
        {"key": "START_WITH_WINDOWS", "label": "Iniciar EDITH con Windows (en la bandeja)", "type": "bool",
         "store": "registry", "desktop_only": True},
    ]},
    {"id": "integraciones", "title": "Casa y cuentas", "icon": "🏠", "fields": [
        {"key": "HA_URL", "label": "Home Assistant: dirección", "type": "url", "allow_empty": True,
         "help": "Ej.: http://homeassistant.local:8123. Luces, enchufes, clima y escenas (nunca cerraduras ni alarmas)."},
        {"key": "HA_TOKEN", "label": "Home Assistant: token de larga duración", "type": "secret", "allow_empty": True,
         "help": "En Home Assistant: tu perfil › Seguridad › Tokens de acceso de larga duración. Se guarda cifrado."},
        {"key": "CALENDAR_ICS_URLS", "label": "Calendario: enlaces iCal", "type": "secret", "allow_empty": True,
         "help": "Google: Configuración del calendario › Dirección secreta en formato iCal. Varios, separados por comas."},
        {"key": "EMAIL_IMAP_HOST", "label": "Correo: servidor IMAP", "type": "text", "allow_empty": True,
         "help": "Gmail: imap.gmail.com · Outlook: outlook.office365.com. Solo lectura: no marca, no borra, no envía."},
        {"key": "EMAIL_ADDRESS", "label": "Correo: tu dirección", "type": "text", "allow_empty": True},
        {"key": "EMAIL_PASSWORD", "label": "Correo: contraseña de aplicación", "type": "secret", "allow_empty": True,
         "help": "No tu contraseña normal: una de aplicación (Gmail: Cuenta › Seguridad › Contraseñas de aplicaciones)."},
        {"key": "EMAIL_IMAP_PORT", "label": "Correo: puerto IMAP", "type": "number", "min": 1, "max": 65535},
    ]},
    {"id": "avanzado", "title": "Avanzado", "icon": "🛠️", "fields": [
        {"key": "OLLAMA_NUM_CTX", "label": "Memoria de trabajo del modelo (tokens)", "type": "number", "min": 4096, "max": 65536,
         "help": "El prompt de EDITH ya ocupa ~4100. Más = conversaciones más largas, pero más VRAM."},
        {"key": "OLLAMA_KEEP_ALIVE", "label": "Tiempo que el modelo queda cargado", "type": "text",
         "help": "Ej.: 30m, 2h, -1 (siempre)."},
        {"key": "OLLAMA_BASE_URL", "label": "Dirección de Ollama", "type": "url"},
        {"key": "EDITH_PORT", "label": "Puerto de EDITH", "type": "text", "restart": True,
         "help": "auto (8000 o el siguiente libre) o un número fijo (necesario para el servidor de la Fase 8)."},
        {"key": "EDITH_HOTKEY", "label": "Atajo global", "type": "text", "restart": True,
         "help": "Ej.: win+shift+e, ctrl+alt+e, u off para desactivarlo."},
    ]},
]
FIELDS = {f["key"]: f for s in SCHEMA for f in s["fields"]}
RESTART_KEYS = {k for k, f in FIELDS.items() if f.get("restart")}


# ---------------------------------------------------------------- estado del primer arranque
def setup_state() -> Dict[str, Any]:
    try:
        return json.loads(SETUP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mark_setup_complete():
    SETUP_FILE.write_text(json.dumps({"completed_at": datetime.now().isoformat(timespec="seconds"), "version": 1},
                                     ensure_ascii=False), encoding="utf-8")


def is_desktop() -> bool:
    return os.environ.get("EDITH_DESKTOP") == "1"


# ---------------------------------------------------------------- iniciar con Windows
def edith_exe() -> Optional[Path]:
    candidates = [Path(sys.executable).with_name("EDITH.exe")] if getattr(sys, "frozen", False) else []
    candidates.append(PROJECT_DIR / "EDITH.exe")
    return next((c for c in candidates if c.exists()), None)


def get_start_with_windows() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "EDITH")
            return True
    except OSError:
        return False


def set_start_with_windows(enabled: bool) -> Optional[str]:
    if sys.platform != "win32":
        return "Solo disponible en Windows."
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enabled:
            exe = edith_exe()
            if not exe:
                return "Falta EDITH.exe: ejecuta install_edith.bat para crearlo."
            winreg.SetValueEx(k, "EDITH", 0, winreg.REG_SZ, f'"{exe}" --tray')
        else:
            try:
                winreg.DeleteValue(k, "EDITH")
            except OSError:
                pass
    return None


# ---------------------------------------------------------------- lectura
def _profile_name() -> str:
    from ..memory.memory_manager import get_memory_manager
    name = get_memory_manager().long_term_data.get("user_name", "")
    return "" if name == "Usuario" else name


def current_values() -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for key, f in FIELDS.items():
        if f.get("store") == "profile":
            values[key] = _profile_name()
        elif f.get("store") == "registry":
            values[key] = get_start_with_windows()
        elif f["type"] == "secret":
            values[key] = MASK if os.getenv(key, "").strip() else ""
        elif f["type"] == "bool":
            values[key] = bool(getattr(Config, key, False)) if hasattr(Config, key) else os.getenv(key, "").lower() in ("1", "true", "yes", "si", "sí")
        elif key == "AUTHORIZED_PHONE_NUMBERS":
            values[key] = ["+" + n for n in Config.AUTHORIZED_PHONE_NUMBERS]
        elif key == "NOTIFY_CHANNELS":
            values[key] = list(Config.NOTIFY_CHANNELS)
        elif key == "HEARTBEAT_NEWS_TOPICS":
            values[key] = ", ".join(Config.HEARTBEAT_NEWS_TOPICS)
        elif key == "OLLAMA_THINK":
            values[key] = Config.OLLAMA_THINK_MODE
        elif key == "OWNER_PHONE_NUMBER":
            values[key] = os.getenv("OWNER_PHONE_NUMBER", "").strip()
        elif key in ("EDITH_PORT", "EDITH_HOTKEY"):
            values[key] = os.getenv(key, "").strip() or ("auto" if key == "EDITH_PORT" else "win+shift+e")
        else:
            values[key] = getattr(Config, key, os.getenv(key, ""))
    return values


# ---------------------------------------------------------------- validación
_PHONE = re.compile(r"^\+?\d{8,15}$")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _validate(key: str, value: Any) -> Tuple[Optional[str], Optional[str]]:
    """Devuelve (valor para el .env, error)."""
    f = FIELDS[key]
    t = f["type"]
    empty_ok = f.get("allow_empty")
    if t == "bool":
        return ("true" if bool(value) else "false"), None
    if t == "multi":
        allowed = {o[0] for o in f["options"]}
        items = [v for v in (value or []) if v in allowed]
        return ",".join(items), None
    if t == "phones":
        raw = value if isinstance(value, list) else re.split(r"[,;\n]+", str(value or ""))
        nums = []
        for n in raw:
            n = re.sub(r"[\s\-()]", "", str(n))
            if not n:
                continue
            if not _PHONE.match(n):
                return None, f"Número no válido: {n}. Usa formato internacional, p. ej. +5215512345678."
            nums.append(n if n.startswith("+") else "+" + n)
        return ",".join(dict.fromkeys(nums)), None
    text = str(value if value is not None else "").strip()
    if not text:
        return ("", None) if empty_ok else (None, f"«{f['label']}» no puede quedar vacío.")
    if any(c in text for c in "\r\n\x00"):  # una línea por ajuste: nada de colar otras claves en el .env
        return None, f"«{f['label']}» no puede tener saltos de línea."
    if t == "phone":
        n = re.sub(r"[\s\-()]", "", text)
        return (n if n.startswith("+") else "+" + n, None) if _PHONE.match(n) else (None, f"Número no válido: {text}")
    if t == "time":
        return (text, None) if _TIME.match(text) else (None, "Hora no válida (usa HH:MM).")
    if t == "timerange":
        parts = text.split("-")
        ok = len(parts) == 2 and all(_TIME.match(p.strip()) for p in parts)
        return ("-".join(p.strip() for p in parts), None) if ok else (None, "Usa el formato 23:00-07:00.")
    if t == "number":
        try:
            n = int(text)
        except ValueError:
            return None, f"«{f['label']}» debe ser un número."
        if not (f.get("min", n) <= n <= f.get("max", n)):
            return None, f"«{f['label']}» debe estar entre {f.get('min')} y {f.get('max')}."
        return str(n), None
    if t == "url":
        if not re.match(r"^https?://[^\s]+$", text):
            return None, f"«{f['label']}» debe empezar por http:// o https://"
        if key == "PUBLIC_BASE_URL" and not text.startswith("https://"):
            return None, "Twilio exige HTTPS en la URL pública."
        return text.rstrip("/"), None
    if t == "select" or t == "voice":
        allowed = {o[0] for o in f["options"]}
        return (text, None) if text in allowed else (None, f"Opción no válida para «{f['label']}».")
    if t == "model":
        return (text, None) if re.match(r"^[\w.\-/]+(:[\w.\-]+)?$", text) else (None, f"Nombre de modelo no válido: {text}")
    if t == "folder":
        p = Path(os.path.expandvars(os.path.expanduser(text)))
        if not p.is_absolute():
            return None, "Indica la ruta completa de la carpeta."
        return str(p), None
    if key == "EDITH_PORT":
        return (text.lower(), None) if text.lower() == "auto" or (text.isdigit() and 1024 <= int(text) <= 65535) else \
            (None, "Puerto: auto o un número entre 1024 y 65535.")
    if key == "EDITH_HOTKEY":
        spec = text.lower().replace(" ", "")
        if spec in ("off", "none", "no"):
            return spec, None
        parts = spec.split("+")
        ok = len(parts) >= 2 and len(parts[-1]) == 1 and all(p in ("ctrl", "alt", "shift", "win") for p in parts[:-1])
        return (spec, None) if ok else (None, "Atajo no válido: usa algo como win+shift+e.")
    if key == "CALENDAR_ICS_URLS":
        urls = [u.strip() for u in text.split(",") if u.strip()]
        bad = [u for u in urls if not re.match(r"^(https?|webcal)://[^\s]+$", u)]
        return (",".join(urls), None) if not bad else (None, "Cada enlace iCal debe empezar por https:// o webcal://")
    if key == "EMAIL_ADDRESS":
        return (text, None) if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text) else (None, "Correo no válido.")
    if key == "OLLAMA_KEEP_ALIVE":
        return (text, None) if re.match(r"^(-1|\d+[smh]?)$", text) else (None, "Usa 30m, 2h o -1.")
    return text, None


# ---------------------------------------------------------------- guardado
def save(values: Dict[str, Any]) -> Dict[str, Any]:
    errors: Dict[str, str] = {}
    to_env: Dict[str, str] = {}
    profile_name: Optional[str] = None
    start_with_windows: Optional[bool] = None
    for key, value in values.items():
        f = FIELDS.get(key)
        if not f or (f.get("desktop_only") and not is_desktop()):
            continue  # solo claves conocidas (y las de escritorio solo en la app): nada arbitrario llega al .env
        if f["type"] == "secret" and value == MASK:
            continue  # sin cambios
        if f.get("store") == "profile":
            profile_name = str(value or "").strip()[:60]
            continue
        if f.get("store") == "registry":
            start_with_windows = bool(value)
            continue
        env_value, err = _validate(key, value)
        if err:
            errors[key] = err
        else:
            to_env[key] = env_value
    if errors:
        return {"ok": False, "errors": errors}

    env_path = Path(config_module.env_path)
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.write_text("# Ajustes de EDITH (editados desde la app)\n", encoding="utf-8")
    changed = []
    for key, val in to_env.items():
        if os.getenv(key, None) != val:
            # Los secretos (tokens, contraseñas) se escriben cifrados con DPAPI; en memoria van en claro
            stored = secret_store.protect(val) if FIELDS[key]["type"] == "secret" else val
            set_key(str(env_path), key, stored, quote_mode="auto", encoding="utf-8")
            os.environ[key] = val
            changed.append(key)
    if profile_name is not None:
        from ..memory.memory_manager import get_memory_manager
        mm = get_memory_manager()
        if mm.long_term_data.get("user_name") != (profile_name or "Usuario"):
            mm.long_term_data["user_name"] = profile_name or "Usuario"
            mm.save_long_term_data()
            changed.append("USER_NAME")
    if start_with_windows is not None and start_with_windows != get_start_with_windows():
        err = set_start_with_windows(start_with_windows)
        if err:
            return {"ok": False, "errors": {"START_WITH_WINDOWS": err}}
        changed.append("START_WITH_WINDOWS")
    Config.reload()
    return {"ok": True, "changed": changed, "restart_required": sorted(set(changed) & RESTART_KEYS),
            "env_file": str(env_path)}
