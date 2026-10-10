"""Memoria semántica ligera: recupera recuerdos relevantes por similitud (TF-IDF + coseno).

No necesita GPU ni servicios externos. Los n-gramas de caracteres toleran
faltas de ortografía y variaciones de conjugación en español.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Dict, List

from sklearn.feature_extraction.text import TfidfVectorizer


def similarity(query: str, texts: List[str]) -> List[float]:
    """Similitud coseno (TF-IDF de n-gramas de caracteres) entre `query` y cada texto."""
    if not texts or not query.strip():
        return [0.0] * len(texts)
    try:
        vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        matrix = vec.fit_transform(texts)
        return [float(x) for x in (matrix @ vec.transform([query]).T).toarray().ravel()]
    except ValueError:  # vocabulario vacío (textos demasiado cortos)
        return [0.0] * len(texts)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


class SemanticMemory:
    def __init__(self, path: str | Path = "data/ml/semantic_memory.json", max_items: int = 5000):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items
        self._lock = threading.Lock()
        self.items: List[Dict] = []
        self._vec = None
        self._matrix = None
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.items = []

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)

    def add(self, text: str, kind: str = "fact", autosave: bool = True) -> bool:
        text = text.strip()
        if len(text) < 8:
            return False
        key = _norm(text)
        with self._lock:
            if any(_norm(i["text"]) == key for i in self.items):
                return False
            self.items.append({"text": text, "kind": kind, "ts": time.time()})
            if len(self.items) > self.max_items:  # olvida lo más viejo, conserva hechos
                facts = [i for i in self.items if i["kind"] == "fact"]
                rest = [i for i in self.items if i["kind"] != "fact"]
                self.items = facts + rest[-(self.max_items - len(facts)):]
            self._vec = self._matrix = None
        if autosave:
            self.save()
        return True

    def _fit(self) -> None:
        self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
        self._matrix = self._vec.fit_transform([i["text"] for i in self.items])

    def search(self, query: str, k: int = 4, min_score: float = 0.32,
               exclude: "set | None" = None, exclude_below: float = 0.55) -> List[Dict]:
        """Busca recuerdos relevantes. `exclude` son textos ya mostrados hace poco:
        se descartan salvo que su similitud sea muy alta (>= exclude_below), para no
        repetir el mismo recuerdo en cada turno cuando la conversación ya cambió de tema."""
        if not self.items or not query.strip():
            return []
        if self._vec is None:
            self._fit()
        scores = (self._matrix @ self._vec.transform([query]).T).toarray().ravel()
        now = time.time()
        results = []
        for idx in scores.argsort()[::-1][: k * 4]:
            s = float(scores[idx])
            if s < min_score:
                break
            item = self.items[idx]
            if exclude and item["text"] in exclude and s < exclude_below:
                continue
            age_days = (now - item["ts"]) / 86400
            s *= 1.0 + 0.1 / (1.0 + age_days / 30)  # ligero bonus por recencia
            results.append({**item, "score": round(s, 3)})
            if len(results) >= k:
                break
        return sorted(results, key=lambda r: -r["score"])[:k]

    def __len__(self) -> int:
        return len(self.items)
