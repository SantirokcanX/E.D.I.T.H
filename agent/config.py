import os
from pathlib import Path
from dotenv import load_dotenv

from .paths import FROZEN, env_file
from .secret_store import decrypt_environ

# .env del proyecto (desarrollo) o, en la app instalada, el de %LOCALAPPDATA%\EDITH
env_path = env_file()
load_dotenv(dotenv_path=env_path)
decrypt_environ()  # secretos guardados desde Ajustes van cifrados con DPAPI

_TRUE = ("1", "true", "yes", "si", "sí")


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).lower().strip() in _TRUE


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _digits(number: str) -> str:
    """Normaliza un teléfono a solo dígitos (con código de país): '+52 1 55-1234' -> '52155...'."""
    return "".join(ch for ch in (number or "") if ch.isdigit())


def _default_vault() -> str:
    dev_vault = Path.home() / "Documents" / "EDITH_proyecto" / "EDITH_p"
    # En la app empaquetada de otra PC no existe la bóveda del proyecto: Documentos\EDITH
    if FROZEN and not dev_vault.is_dir():
        return str(Path.home() / "Documents" / "EDITH")
    return str(dev_vault)

class Config:
    @classmethod
    def reload(cls):
        """Carga (o recarga) la configuración desde el archivo .env."""
        load_dotenv(dotenv_path=env_path, override=True)
        decrypt_environ()
        cls.PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower().strip()

        # Ollama settings
        cls.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        # Modelo para respuestas rápidas (sin razonamiento) y, opcionalmente, otro para pensar a fondo.
        # Si OLLAMA_DEEP_MODEL está vacío se usa OLLAMA_MODEL para todo (sirve con modelos híbridos).
        cls.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
        cls.OLLAMA_DEEP_MODEL = os.getenv("OLLAMA_DEEP_MODEL", "qwen3:4b").strip()
        # Velocidad: mantener el modelo cargado en RAM/VRAM entre mensajes y limitar el contexto
        cls.OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip()
        # Visión local (fotos por WhatsApp, pantalla): modelo multimodal de Ollama; vacío = sin visión local
        cls.VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:4b").strip()
        cls.OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
        # auto = EDITH decide por consulta (rápido para charla, profundo para problemas difíciles)
        # true = siempre razona; false = siempre responde directo
        think = os.getenv("OLLAMA_THINK", "auto").lower().strip()
        cls.OLLAMA_THINK_MODE = "auto" if think == "auto" else ("true" if think in _TRUE else "false")
        cls.OLLAMA_THINK = cls.OLLAMA_THINK_MODE == "true"
        cls.OLLAMA_WARMUP = _flag("OLLAMA_WARMUP", "true")

        # Gemini settings
        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
        cls.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        # Reasoning Agent settings
        cls.MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "6"))
        cls.SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

        # Machine Learning (agent/ml)
        cls.ML_ENABLED = _flag("ML_ENABLED", "true")
        cls.ML_AUTO_ROUTE = _flag("ML_AUTO_ROUTE", "true")
        cls.ML_AUTO_THRESHOLD = float(os.getenv("ML_AUTO_THRESHOLD", "0.6"))
        # Razonamiento automático: certeza mínima del clasificador aprendido para pensar a fondo
        cls.DEEP_ML_THRESHOLD = float(os.getenv("DEEP_ML_THRESHOLD", "0.75"))

        # Obsidian (bóveda = memoria externa de EDITH)
        cls.OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "").strip() or _default_vault()
        cls.OBSIDIAN_AUTO_SYNC = _flag("OBSIDIAN_AUTO_SYNC", "false")
        # Fase 2: copiar a la bóveda los diagramas y las notas del día del workspace
        cls.OBSIDIAN_SAVE_WORKSPACE = _flag("OBSIDIAN_SAVE_WORKSPACE", "true")
        # Fase 12: navegador propio de EDITH (Playwright). msedge = el Microsoft Edge instalado
        cls.BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "msedge").strip()
        # Fase 13 (IoT): Home Assistant. Fase 11: calendario (enlaces iCal) y correo IMAP de solo lectura
        cls.HA_URL = os.getenv("HA_URL", "").strip().rstrip("/")
        cls.HA_TOKEN = os.getenv("HA_TOKEN", "").strip()
        cls.CALENDAR_ICS_URLS = [u.strip() for u in os.getenv("CALENDAR_ICS_URLS", "").split(",") if u.strip()]
        cls.EMAIL_IMAP_HOST = os.getenv("EMAIL_IMAP_HOST", "").strip()
        cls.EMAIL_IMAP_PORT = _int("EMAIL_IMAP_PORT", 993)
        cls.EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "").strip()
        cls.EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "").strip()

        # Voz elegida en Ajustes (elvira, dalia, ximena, salome, viernes)
        cls.EDITH_VOICE = os.getenv("EDITH_VOICE", "elvira").strip().lower()
        # Voz: si edge-tts falla (sin internet), usar las voces SAPI5 de Windows
        cls.VOICE_OFFLINE_FALLBACK = _flag("VOICE_OFFLINE_FALLBACK", "true")
        # «Oye EDITH»: micrófono de la interfaz -> Whisper local (agent/voice/wake_word.py)
        cls.WAKE_WORD_ENABLED = _flag("WAKE_WORD_ENABLED", "true")
        cls.WAKE_WORD_SENSITIVITY = os.getenv("WAKE_WORD_SENSITIVITY", "normal").strip().lower()
        cls.WAKE_WORD_MODEL = os.getenv("WAKE_WORD_MODEL", "base").strip()

        # --- Canales remotos (Fases 9 y 10) ---
        # Lista blanca: solo estos números pueden hablar con EDITH por WhatsApp o teléfono.
        # Vacía = nadie (falla cerrado). Formato internacional, p. ej. +5215512345678
        cls.AUTHORIZED_PHONE_NUMBERS = [
            n for n in (_digits(x) for x in os.getenv("AUTHORIZED_PHONE_NUMBERS", "").split(",")) if n
        ]
        # A quién avisa EDITH (WhatsApp/llamadas). Por defecto, el primer número autorizado.
        cls.OWNER_PHONE_NUMBER = _digits(os.getenv("OWNER_PHONE_NUMBER", "")) or (
            cls.AUTHORIZED_PHONE_NUMBERS[0] if cls.AUTHORIZED_PHONE_NUMBERS else "")
        # Desde canales remotos EDITH NO ejecuta PowerShell ni abre apps salvo que lo actives aquí
        cls.REMOTE_ALLOW_SYSTEM_TOOLS = _flag("REMOTE_ALLOW_SYSTEM_TOOLS", "false")

        # WhatsApp (bridge local con Baileys en bridges/whatsapp)
        cls.WHATSAPP_ENABLED = _flag("WHATSAPP_ENABLED", "false")
        cls.WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:3100").rstrip("/")
        # auto = responde con nota de voz cuando tú mandas nota de voz; always / never
        cls.WHATSAPP_VOICE_REPLIES = os.getenv("WHATSAPP_VOICE_REPLIES", "auto").lower().strip()

        # Transcripción local de notas de voz (faster-whisper)
        cls.WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small").strip()
        cls.WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip()
        cls.WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip()

        # Telefonía (Twilio Voice)
        cls.TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        cls.TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        cls.TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "").strip()
        # URL pública HTTPS por la que Twilio llega a EDITH (Tailscale Funnel, ngrok... ver Fase 8)
        cls.PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
        # relay = tiempo real (ConversationRelay, requiere alta en Twilio); gather = por turnos
        cls.TWILIO_VOICE_MODE = os.getenv("TWILIO_VOICE_MODE", "gather").lower().strip()
        cls.TWILIO_LANGUAGE = os.getenv("TWILIO_LANGUAGE", "es-MX").strip()
        cls.TWILIO_SAY_VOICE = os.getenv("TWILIO_SAY_VOICE", "Polly.Mia-Neural").strip()
        cls.TWILIO_RELAY_VOICE = os.getenv("TWILIO_RELAY_VOICE", "").strip()

        # --- Autonomía proactiva (Fase 11) ---
        cls.HEARTBEAT_ENABLED = _flag("HEARTBEAT_ENABLED", "true")
        cls.HEARTBEAT_MINUTES = max(1, int(os.getenv("HEARTBEAT_MINUTES", "15")))
        cls.MORNING_BRIEFING_TIME = os.getenv("MORNING_BRIEFING_TIME", "08:00").strip()
        cls.QUIET_HOURS = os.getenv("QUIET_HOURS", "23:00-07:00").strip()
        cls.ESCALATE_AFTER_MINUTES = int(os.getenv("ESCALATE_AFTER_MINUTES", "10"))
        cls.HEARTBEAT_NEWS_TOPICS = [t.strip() for t in os.getenv("HEARTBEAT_NEWS_TOPICS", "").split(",") if t.strip()]
        cls.NOTIFY_CHANNELS = [c.strip() for c in os.getenv("NOTIFY_CHANNELS", "ui,toast,whatsapp").split(",") if c.strip()]
        # Fase 6: aviso de Windows si una respuesta tarda más de esto y no estás mirando EDITH (0 = nunca)
        cls.LONG_TASK_NOTIFY_SECONDS = _int("LONG_TASK_NOTIFY_SECONDS", 25) or 10 ** 9

        # --- Seguridad de la interfaz y la API (Fase 14) ---
        # Nombres o IPs extra con los que se puede llegar a EDITH (Tailscale, IP de la red local...).
        # localhost/127.0.0.1 y el host de PUBLIC_BASE_URL ya están permitidos.
        cls.EDITH_ALLOWED_HOSTS = [h.strip().lower() for h in os.getenv("EDITH_ALLOWED_HOSTS", "").split(",") if h.strip()]
        # true = al abrir la interfaz desde la propia máquina (127.0.0.1) entra sin pedir el enlace con token
        cls.EDITH_LOCAL_AUTOLOGIN = _flag("EDITH_LOCAL_AUTOLOGIN", "true")
        # Límites por minuto (0 = sin límite): peticiones desde otro dispositivo, consultas al modelo
        # por cliente e intentos con un token incorrecto por IP
        cls.RATE_LIMIT_PER_MINUTE = _int("RATE_LIMIT_PER_MINUTE", 240)
        cls.CHAT_LIMIT_PER_MINUTE = _int("CHAT_LIMIT_PER_MINUTE", 20)
        cls.AUTH_FAILURES_PER_MINUTE = _int("AUTH_FAILURES_PER_MINUTE", 10)


Config.reload()
