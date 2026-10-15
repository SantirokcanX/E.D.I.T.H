import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env en la raíz del proyecto
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

_TRUE = ("1", "true", "yes", "si", "sí")


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).lower().strip() in _TRUE


def _default_vault() -> str:
    return str(Path.home() / "Documents" / "EDITH_proyecto" / "EDITH_p")

class Config:
    @classmethod
    def reload(cls):
        """Carga (o recarga) la configuración desde el archivo .env."""
        load_dotenv(dotenv_path=env_path, override=True)
        cls.PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower().strip()

        # Ollama settings
        cls.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        cls.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:latest")
        # Velocidad: mantener el modelo cargado en RAM/VRAM entre mensajes y limitar el contexto
        cls.OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m").strip()
        cls.OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
        # true = razonamiento <think> completo; false = respuestas directas (mucho más rápidas)
        cls.OLLAMA_THINK = _flag("OLLAMA_THINK", "true")
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

        # Obsidian (bóveda = memoria externa de EDITH)
        cls.OBSIDIAN_VAULT_PATH = os.getenv("OBSIDIAN_VAULT_PATH", "").strip() or _default_vault()
        cls.OBSIDIAN_AUTO_SYNC = _flag("OBSIDIAN_AUTO_SYNC", "false")

        # Voz: si edge-tts falla (sin internet), usar las voces SAPI5 de Windows
        cls.VOICE_OFFLINE_FALLBACK = _flag("VOICE_OFFLINE_FALLBACK", "true")


Config.reload()
