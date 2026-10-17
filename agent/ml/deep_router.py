"""¿Pensar a fondo o responder rápido? Aprende de cuándo el usuario elige 🔬 Profundo o ⚡ Rápido.

En el modo automático, la heurística de palabras clave (needs_deep_thinking) sigue mandando; este
clasificador solo AÑADE casos que la heurística no ve, y únicamente cuando ya aprendió del usuario
(MIN_UPDATES elecciones explícitas) y está muy seguro (DEEP_ML_THRESHOLD). Se guarda en
data/ml/deep_router.joblib, en la carpeta de datos de EDITH.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier

from ..paths import DATA_DIR

LABELS = ["fast", "deep"]
MIN_UPDATES = 5
SEEDS = {
    "deep": [
        "resuelve la ecuación 3x + 5 = 20", "demuestra que la raíz de 2 es irracional",
        "calcula la probabilidad de sacar dos ases", "por qué falla este código", "depura esta función",
        "analiza paso a paso este acertijo lógico", "optimiza este algoritmo y explica su complejidad",
        "encuentra el error en este razonamiento", "cuánto es 17 por 23 menos 45",
        "compara rigurosamente estas dos demostraciones",
    ],
    "fast": [
        "hola", "qué tal", "gracias", "pon música", "abre la calculadora", "qué hora es",
        "traduce buenos días al inglés", "recuérdame comprar leche", "dame un sinónimo de feliz",
        "cuéntame un chiste", "resume esta nota", "cómo se dice gato en francés",
    ],
}


class DeepThinkRouter:
    def __init__(self, path: Path = DATA_DIR / "ml" / "deep_router.joblib", seed: int = 7):
        self.path = Path(path)
        self._lock = threading.Lock()
        self.vec = HashingVectorizer(n_features=2 ** 16, analyzer="char_wb", ngram_range=(2, 4),
                                     alternate_sign=False, norm="l2", lowercase=True)
        self.clf = SGDClassifier(loss="log_loss", alpha=1e-4, random_state=seed, tol=None, max_iter=1)
        self.updates = 0
        if not self._load():
            self._bootstrap()

    def _bootstrap(self, epochs: int = 12):
        texts = [t for label in LABELS for t in SEEDS[label]]
        y = np.array([label for label in LABELS for _ in SEEDS[label]])
        X = self.vec.transform(texts)
        rng = np.random.default_rng(0)
        for _ in range(epochs):
            idx = rng.permutation(len(y))
            self.clf.partial_fit(X[idx], y[idx], classes=np.array(LABELS))

    def _load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            data = joblib.load(self.path)
            self.clf, self.updates = data["clf"], int(data["updates"])
            return True
        except Exception:
            return False

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            joblib.dump({"clf": self.clf, "updates": self.updates}, self.path)

    def prob_deep(self, text: str) -> float:
        with self._lock:
            proba = self.clf.predict_proba(self.vec.transform([text]))[0]
        return float(dict(zip(self.clf.classes_, proba)).get("deep", 0.0))

    def learn(self, text: str, deep: bool):
        """El usuario eligió explícitamente cómo quería esta respuesta."""
        X = self.vec.transform([text])
        with self._lock:
            for _ in range(3):
                self.clf.partial_fit(X, np.array(["deep" if deep else "fast"]))
            self.updates += 1
        self.save()

    def wants_deep(self, text: str, threshold: float) -> bool:
        return self.updates >= MIN_UPDATES and self.prob_deep(text) >= threshold


_router: Optional[DeepThinkRouter] = None
_router_lock = threading.Lock()


def get_deep_router() -> DeepThinkRouter:
    global _router
    with _router_lock:
        if _router is None:
            _router = DeepThinkRouter()
        return _router
