"""Wake Word and Voice Detection system for EDITH ('Oye EDITH' / 'EDITH')."""

import threading
import time
from typing import Callable, Optional

# Palabras clave de activación
WAKE_WORDS = ["edith", "oye edith", "hey edith", "hola edith", "edit", "oye edit"]


class WakeWordDetector:
    """Detecta la llamada de voz ('Oye EDITH') y dispara la captura de instrucciones."""

    def __init__(self, on_wake: Optional[Callable[[], None]] = None):
        self.on_wake = on_wake
        self.is_listening = False
        self._thread: Optional[threading.Thread] = None

    def is_wake_phrase(self, text: str) -> bool:
        """Determina si un texto transcrito contiene la palabra clave de activación."""
        if not text:
            return False
        clean = text.lower().strip()
        return any(w in clean for w in WAKE_WORDS)

    def extract_command_after_wake(self, text: str) -> str:
        """Extrae la orden que sigue a la palabra clave si el usuario habló corrido."""
        clean = text.lower().strip()
        for w in WAKE_WORDS:
            if w in clean:
                parts = clean.split(w, 1)
                if len(parts) > 1 and parts[1].strip():
                    return parts[1].strip()
        return clean


_global_wake_detector: Optional[WakeWordDetector] = None

def get_wake_detector() -> WakeWordDetector:
    global _global_wake_detector
    if _global_wake_detector is None:
        _global_wake_detector = WakeWordDetector()
    return _global_wake_detector
