import os
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env en la raíz del proyecto
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Config:
    PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower().strip()
    
    # Ollama settings
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:latest")
    
    # Gemini settings
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # Reasoning Agent settings
    MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "6"))
    SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

    @classmethod
    def reload(cls):
        """Recarga la configuración desde el archivo .env."""
        load_dotenv(dotenv_path=env_path, override=True)
        cls.PROVIDER = os.getenv("AI_PROVIDER", "ollama").lower().strip()
        cls.OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        cls.OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-r1:latest")
        cls.GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
        cls.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        cls.MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "6"))
        cls.SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
