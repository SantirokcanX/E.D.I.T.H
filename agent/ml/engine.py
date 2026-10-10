"""Fachada del subsistema ML de EDITH (enrutador + memoria semántica + historial inteligente)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from .router import ROUTES, OnlineRouter
from .semantic_memory import SemanticMemory, similarity

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DIR = BASE_DIR / "data" / "ml"
SESSIONS_DIR = BASE_DIR / "data" / "sessions"

ROUTE_HINTS = {
    "web_search": "esta consulta probablemente necesita datos actuales: usa `web_search` / `read_web_page`.",
    "workspace": "esta consulta probablemente pide crear o editar un archivo: usa `save_to_workspace`.",
}


@dataclass
class Analysis:
    route: str
    confidence: float
    probs: Dict[str, float]
    memories: List[Dict] = field(default_factory=list)

    @property
    def context(self) -> str:
        if not self.memories:
            return ""
        lines = "\n".join(f"- {m['text']}" for m in self.memories)
        return f"[Recuerdos relevantes recuperados por ML]\n{lines}"


class MLEngine:
    def __init__(self, base_dir: str | Path = DEFAULT_DIR, memory_cooldown: int = 4):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)
        self.router = OnlineRouter(self.base / "router.joblib")
        self.memory = SemanticMemory(self.base / "semantic_memory.json")
        self.events = self.base / "events.jsonl"
        # Evita que el MISMO recuerdo se repita turno tras turno cuando ya se cambió de tema
        self._memory_cooldown = memory_cooldown
        self._recently_shown: List[str] = []

    # ---------- inferencia ----------
    def analyze(self, query: str, k: int = 4) -> Analysis:
        route, conf, probs = self.router.predict(query)
        memories = self.memory.search(query, k=k, exclude=set(self._recently_shown))
        for m in memories:
            if m["text"] in self._recently_shown:
                self._recently_shown.remove(m["text"])
            self._recently_shown.append(m["text"])
        self._recently_shown = self._recently_shown[-self._memory_cooldown:]
        return Analysis(route, conf, probs, memories)

    def prompt_context(self, query: str, k: int = 3, hint_threshold: float = 0.7) -> str:
        """Texto para el prompt del sistema: recuerdos relevantes + sugerencia de herramienta."""
        a = self.analyze(query, k=k)
        parts = []
        if a.memories:
            parts.append(a.context)
        hint = ROUTE_HINTS.get(a.route)
        if hint and a.confidence >= hint_threshold:
            parts.append(f"[Sugerencia del clasificador interno ({a.confidence:.0%})]: {hint}")
        return ("\n" + "\n".join(parts) + "\n") if parts else ""

    @staticmethod
    def rank(query: str, texts: List[str], k: int = 5, min_score: float = 0.1) -> List[int]:
        """Índices de `texts` ordenados por relevancia respecto a `query` (solo los relevantes)."""
        scores = similarity(query, texts)
        order = sorted(range(len(texts)), key=lambda i: -scores[i])
        return [i for i in order if scores[i] >= min_score][:k]

    # ---------- historial inteligente ----------
    @staticmethod
    def _turns(messages: List[Dict]) -> Tuple[List[Dict], List[List[Dict]]]:
        system = messages[:1] if messages and messages[0].get("role") == "system" else []
        turns: List[List[Dict]] = []
        cur: List[Dict] = []
        for m in messages[len(system):]:
            if m.get("role") == "user" and cur:
                turns.append(cur)
                cur = []
            cur.append(m)
        if cur:
            turns.append(cur)
        return system, turns

    def compress_history(self, messages: List[Dict], query: str,
                         keep_last_turns: int = 2, k_relevant: int = 5) -> List[Dict]:
        """Conserva solo el o los últimos turnos tal cual (continuidad inmediata) y,
        de TODO lo anterior, únicamente los turnos cuyo tema de verdad se relaciona con
        `query` — así un tema viejo (p. ej. un ejercicio de código ya resuelto) no sigue
        apareciendo una vez que la charla ya cambió de asunto. Reduce además el contexto
        enviado al modelo."""
        system, turns = self._turns(messages)
        if len(turns) <= keep_last_turns + k_relevant:
            return list(messages)
        old, recent = turns[:-keep_last_turns], turns[-keep_last_turns:]

        condensed: List[List[Dict]] = []
        for t in old:
            user = next((m for m in t if m.get("role") == "user"), None)
            final = next((m for m in reversed(t)
                          if m.get("role") == "assistant" and isinstance(m.get("content"), str)
                          and m["content"].strip()), None)
            if user and final:
                condensed.append([
                    {"role": "user", "content": str(user.get("content", ""))},
                    {"role": "assistant", "content": final["content"][:1200]},
                ])
        if not condensed:
            return system + [m for t in recent for m in t]

        texts = [t[0]["content"] + " " + t[1]["content"] for t in condensed]
        keep = sorted(self.rank(query, texts, k=k_relevant, min_score=0.3))
        out = system + [m for i in keep for m in condensed[i]]
        return out + [m for t in recent for m in t]

    # ---------- aprendizaje ----------
    def feedback(self, query: str, correct_route: str, weight: float = 1.0) -> None:
        """Corrección explícita del usuario: la señal de aprendizaje fiable."""
        self.router.learn(query, correct_route, weight)
        self._log("feedback", query=query, route=correct_route)

    def log_query(self, query: str, route: Optional[str] = None, used_team: bool = False) -> None:
        self._log("query", query=query, predicted=route, coworking=used_team)

    def remember(self, text: str, kind: str = "fact") -> bool:
        return self.memory.add(text, kind)

    def remember_turn(self, user_text: str) -> bool:
        """Guarda el mensaje del usuario como recuerdo recuperable en futuras charlas."""
        return len(user_text) >= 20 and self.memory.add(user_text, "history")

    def train_from_sessions(self, sessions_dir: str | Path = SESSIONS_DIR) -> int:
        added = 0
        for f in Path(sessions_dir).glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            for msg in self._user_messages(data):
                if len(msg) >= 20 and self.memory.add(msg, "history", autosave=False):
                    added += 1
        self.memory.save()
        self.router.save()
        return added

    @classmethod
    def _user_messages(cls, node) -> Iterator[str]:
        if isinstance(node, dict):
            content = node.get("content", node.get("text"))
            if node.get("role") == "user" and isinstance(content, str):
                yield content
            for v in node.values():
                if isinstance(v, (dict, list)):
                    yield from cls._user_messages(v)
        elif isinstance(node, list):
            for v in node:
                yield from cls._user_messages(v)

    def status(self) -> Dict:
        return {
            "rutas": ROUTES,
            "actualizaciones_router": self.router.updates,
            "recuerdos": len(self.memory),
        }

    def _log(self, event: str, **data) -> None:
        try:
            with self.events.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.time(), "event": event, **data}, ensure_ascii=False) + "\n")
        except OSError:
            pass


_engine: Optional[MLEngine] = None


def get_ml_engine() -> MLEngine:
    """Instancia compartida (agente, CLI e IDE usan el mismo modelo)."""
    global _engine
    if _engine is None:
        _engine = MLEngine()
    return _engine
