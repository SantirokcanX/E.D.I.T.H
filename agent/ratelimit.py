"""Límite de peticiones (Fase 14): que nadie sature la GPU ni pruebe tokens a lo bestia.

Tres ventanas deslizantes de 60 s (los límites se cambian en .env):
  - RATE_LIMIT_PER_MINUTE: peticiones HTTP desde otro dispositivo (la propia laptop no cuenta).
  - CHAT_LIMIT_PER_MINUTE: consultas al modelo por cliente (chat y WhatsApp).
  - AUTH_FAILURES_PER_MINUTE: intentos con un token incorrecto; al pasarse, esa IP espera.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from agent.config import Config

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class SlidingWindow:
    def __init__(self, limit_attr: str, window: float = 60.0):
        self.limit_attr = limit_attr  # se lee de Config en cada uso: Ajustes puede cambiarlo en vivo
        self.window = window
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return int(getattr(Config, self.limit_attr, 0) or 0)

    def _trim(self, q: Deque[float], now: float):
        while q and now - q[0] >= self.window:
            q.popleft()

    def hit(self, key: str) -> bool:
        """Registra un intento. False si ya se pasó del límite (y no lo registra)."""
        if self.limit <= 0:
            return True  # 0 = sin límite
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            self._trim(q, now)
            if len(q) >= self.limit:
                return False
            q.append(now)
            if len(self._hits) > 5000:  # no crecer sin fin con IPs que ya no vuelven
                for k in [k for k, v in self._hits.items() if not v][:1000]:
                    del self._hits[k]
            return True

    def blocked(self, key: str) -> bool:
        if self.limit <= 0:
            return False
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return False
            self._trim(q, now)
            return len(q) >= self.limit

    def retry_after(self, key: str) -> int:
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 1
            return max(1, int(self.window - (time.monotonic() - q[0])) + 1)

    def reset(self):
        with self._lock:
            self._hits.clear()


http_remote = SlidingWindow("RATE_LIMIT_PER_MINUTE")
chat = SlidingWindow("CHAT_LIMIT_PER_MINUTE")
auth_failures = SlidingWindow("AUTH_FAILURES_PER_MINUTE")


def client_ip(scope) -> str:
    return (scope.get("client") or ("", 0))[0] or ""


def is_loopback(ip: str) -> bool:
    return ip in LOOPBACK or ip.startswith("127.")


def reset_all():
    for w in (http_remote, chat, auth_failures):
        w.reset()
