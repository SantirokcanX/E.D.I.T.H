"""Enrutador con aprendizaje incremental (online learning).

Decide qué estrategia conviene para una consulta:
  direct     -> responder con el modelo directamente
  web_search -> necesita información actual de internet
  coworking  -> problema complejo, conviene el equipo multi-agente
  workspace  -> crear/editar archivos o código en el workspace

Arranca con ejemplos semilla y mejora con cada corrección (partial_fit),
guardando el modelo en disco entre sesiones.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Tuple

import joblib
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier

ROUTES = ["direct", "web_search", "coworking", "workspace"]

SEEDS: Dict[str, list] = {
    "direct": [
        "hola", "qué es una variable", "explícame qué es la recursión",
        "cómo estás", "define entropía", "traduce esta frase al inglés",
        "what is a closure", "resume este texto", "dame un consejo para estudiar",
        "cuál es la diferencia entre lista y tupla", "gracias",
        "qué es un decorador en python", "cómo funciona una api rest",
        "explica qué es machine learning", "para qué sirve git",
        "por qué mi código da error de indentación", "qué significa async",
    ],
    "web_search": [
        "últimas noticias de tecnología", "cuál es el precio del dólar hoy",
        "busca en internet información sobre", "quién ganó el partido de ayer",
        "clima en Aguascalientes esta semana", "latest version of python",
        "investiga las novedades de", "busca artículos recientes sobre",
        "cuánto cuesta actualmente", "qué está pasando con",
    ],
    "coworking": [
        "analiza a fondo este problema desde varios ángulos",
        "haz un estudio completo comparando alternativas y critica cada una",
        "diseña una estrategia detallada con riesgos y contrapuntos",
        "investiga, audita y sintetiza un informe profundo",
        "evalúa pros y contras de esta arquitectura y propón un plan",
        "necesito un análisis crítico y un plan de acción completo",
        "compare in depth these approaches and challenge the assumptions",
    ],
    "workspace": [
        "crea un archivo con el código de", "escribe un script en python que",
        "guarda este reporte en el workspace", "edita el archivo main.py",
        "genera un archivo html con", "crea un documento con el resumen",
        "write a file called", "programa una función que lea un csv y la guarda",
    ],
}


class OnlineRouter:
    def __init__(self, path: str | Path = "data/ml/router.joblib", seed: int = 42):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.vec = HashingVectorizer(
            n_features=2 ** 16, analyzer="char_wb", ngram_range=(2, 4),
            alternate_sign=False, norm="l2", lowercase=True,
        )
        self.clf = SGDClassifier(
            loss="log_loss", alpha=1e-4, random_state=seed, tol=None, max_iter=1,
        )
        self.updates = 0
        if not self._load():
            self._bootstrap()
            self.save()

    def _bootstrap(self, epochs: int = 12) -> None:
        texts = [t for r in ROUTES for t in SEEDS[r]]
        labels = [r for r in ROUTES for _ in SEEDS[r]]
        X = self.vec.transform(texts)
        y = np.array(labels)
        rng = np.random.default_rng(0)
        for _ in range(epochs):
            idx = rng.permutation(len(y))
            self.clf.partial_fit(X[idx], y[idx], classes=np.array(ROUTES))

    def _load(self) -> bool:
        if not self.path.exists():
            return False
        try:
            data = joblib.load(self.path)
            self.clf, self.updates = data["clf"], data["updates"]
            return True
        except Exception:
            return False

    def save(self) -> None:
        with self._lock:
            joblib.dump({"clf": self.clf, "updates": self.updates}, self.path)

    def predict(self, text: str) -> Tuple[str, float, Dict[str, float]]:
        X = self.vec.transform([text])
        proba = self.clf.predict_proba(X)[0]
        probs = {c: float(p) for c, p in zip(self.clf.classes_, proba)}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

    def learn(self, text: str, route: str, weight: float = 1.0, save_every: int = 1) -> None:
        if route not in ROUTES:
            raise ValueError(f"Ruta desconocida: {route}")
        X = self.vec.transform([text])
        with self._lock:
            for _ in range(3):  # pocas pasadas: aprende rápido sin olvidar lo previo
                self.clf.partial_fit(X, np.array([route]), sample_weight=[weight])
            self.updates += 1
        if self.updates % save_every == 0:
            self.save()
