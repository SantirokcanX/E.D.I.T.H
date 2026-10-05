"""Providers package for AI models."""

from typing import Optional
from .base import BaseLLMProvider, AgentStepResponse, ToolCall
from .ollama_provider import OllamaProvider
from .gemini_provider import GeminiProvider
from ..config import Config


def get_provider(provider_name: Optional[str] = None, model: Optional[str] = None) -> BaseLLMProvider:
    """
    Fábrica para instanciar el proveedor de LLM adecuado según configuración o argumento.
    """
    name = (provider_name or Config.PROVIDER).lower().strip()
    
    if name == "gemini":
        m = model or Config.GEMINI_MODEL
        return GeminiProvider(api_key=Config.GEMINI_API_KEY, model=m)
    elif name == "ollama":
        m = model or Config.OLLAMA_MODEL
        return OllamaProvider(base_url=Config.OLLAMA_BASE_URL, model=m)
    else:
        raise ValueError(f"Proveedor no soportado: '{name}'. Opciones disponibles: 'ollama', 'gemini'.")


__all__ = ["BaseLLMProvider", "AgentStepResponse", "ToolCall", "OllamaProvider", "GeminiProvider", "get_provider"]
