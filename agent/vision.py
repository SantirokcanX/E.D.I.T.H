"""Visión: describir imágenes (fotos por WhatsApp, capturas de pantalla).

Orden de preferencia:
  1. Un modelo de visión local en Ollama (VISION_MODEL, por defecto qwen3-vl:4b): nada sale de la laptop.
  2. Gemini, si hay GEMINI_API_KEY (la imagen viaja a Google).
Si no hay ninguno, devuelve None y quien llama explica cómo activarlo.
"""

import base64
import os
from typing import Optional, Tuple

import httpx

from .config import Config

PROMPT = ("Eres los ojos de E.D.I.T.H. Describe con precisión, en español, lo que se ve en la imagen y responde a "
          "la petición del usuario. Si hay texto, transcríbelo. No inventes detalles que no se vean.\n\nPetición: {q}")


def local_model_installed() -> bool:
    model = (Config.VISION_MODEL or "").strip()
    if not model:
        return False
    try:
        tags = httpx.get(f"{Config.OLLAMA_BASE_URL}/api/tags", timeout=4).json().get("models", [])
    except Exception:
        return False
    names = {m.get("name", "") for m in tags}
    return model in names or f"{model}:latest" in names


def _ollama(image: bytes, question: str) -> str:
    r = httpx.post(f"{Config.OLLAMA_BASE_URL}/api/chat", timeout=180.0, json={
        "model": Config.VISION_MODEL, "stream": False, "think": False,
        "keep_alive": Config.OLLAMA_KEEP_ALIVE,
        "messages": [{"role": "user", "content": PROMPT.format(q=question),
                      "images": [base64.b64encode(image).decode("ascii")]}],
    })
    r.raise_for_status()
    return (r.json().get("message") or {}).get("content", "").strip()


def _gemini(image: bytes, mime: str, question: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"].strip())
    resp = client.models.generate_content(model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                                          contents=[types.Part.from_bytes(data=image, mime_type=mime),
                                                    PROMPT.format(q=question)])
    return (resp.text or "").strip()


def describe_image(image: bytes, question: str = "", mime: str = "image/jpeg") -> Tuple[Optional[str], str]:
    """(descripción o None, quién la hizo: 'local:<modelo>' | 'gemini' | motivo si no se pudo)."""
    question = question.strip() or "¿Qué hay en esta imagen?"
    if local_model_installed():
        try:
            text = _ollama(image, question)
            if text:
                return text, f"local:{Config.VISION_MODEL}"
        except Exception as e:
            print(f"[Visión] el modelo local falló: {e}")
    if os.environ.get("GEMINI_API_KEY", "").strip():
        try:
            text = _gemini(image, mime, question)
            if text:
                return text, "gemini"
        except Exception as e:
            print(f"[Visión] Gemini falló: {e}")
    return None, (f"no hay modelo de visión: descarga «{Config.VISION_MODEL}» en Ajustes › Modelos de IA "
                  "(unos 3 GB) o pon una GEMINI_API_KEY")
