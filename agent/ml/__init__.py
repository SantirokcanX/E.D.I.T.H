"""Subsistema de Machine Learning de EDITH.

- OnlineRouter:   clasificador incremental que decide la ruta de una consulta.
- SemanticMemory: memoria vectorial (TF-IDF) con búsqueda por similitud.
- MLEngine:       fachada: contexto para el prompt, historial inteligente y aprendizaje.
"""

from .engine import Analysis, MLEngine, get_ml_engine
from .router import ROUTES, OnlineRouter
from .semantic_memory import SemanticMemory, similarity

__all__ = ["MLEngine", "Analysis", "OnlineRouter", "SemanticMemory", "ROUTES",
           "get_ml_engine", "similarity"]
