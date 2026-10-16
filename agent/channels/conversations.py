"""Un agente EDITH por canal y contacto, con su propia memoria de sesiones y herramientas limitadas."""

import threading
from typing import Dict, Optional

from ..config import Config
from ..core.reasoning_agent import ReasoningAgent
from ..memory.memory_manager import MemoryManager
from ..tools import LOCAL_ONLY_TOOLS
from .security import canonical_number

CHANNEL_NOTES = {
    "whatsapp": (
        "[CANAL: WhatsApp] Estás hablando por WhatsApp desde el celular del usuario. Responde breve y directo "
        "(2-6 frases o una lista corta). WhatsApp NO renderiza LaTeX ni tablas: escribe fórmulas en texto simple "
        "(x², √2, 1/3) y usa *negritas* con un asterisco. Si el usuario confirma algo con 'ok' o 'listo', no repitas todo."
    ),
    "phone": (
        "[CANAL: llamada telefónica] Todo lo que escribas se lee en voz alta por teléfono. Responde en 1-3 frases "
        "habladas y naturales, sin formato, sin listas, sin emojis, sin LaTeX ni código. Si algo requiere mucho detalle, "
        "ofrece enviarlo por WhatsApp o guardarlo en Obsidian."
    ),
}
TITLES = {"whatsapp": "💬 WhatsApp", "phone": "📞 Llamada"}

_agents: Dict[str, ReasoningAgent] = {}
_lock = threading.Lock()


def get_channel_agent(provider, channel: str, contact: str) -> ReasoningAgent:
    """Agente persistente por (canal, contacto): retoma la última charla de ese contacto."""
    key = f"{channel}_{canonical_number(contact) or 'anon'}"
    with _lock:
        agent = _agents.get(key)
        if agent is None:
            memory = MemoryManager(session_prefix=key, default_title=TITLES.get(channel, channel))
            blocked = set() if Config.REMOTE_ALLOW_SYSTEM_TOOLS else set(LOCAL_ONLY_TOOLS)
            agent = ReasoningAgent(provider=provider, max_iterations=min(Config.MAX_ITERATIONS, 4),
                                   memory=memory, blocked_tools=blocked,
                                   channel_note=CHANNEL_NOTES.get(channel, ""))
            _agents[key] = agent
        return agent


def reset_channel_agent(channel: str, contact: str) -> Optional[str]:
    key = f"{channel}_{canonical_number(contact) or 'anon'}"
    with _lock:
        agent = _agents.get(key)
    if agent:
        agent.reset_history()
        return agent.memory.current_session_id
    return None
