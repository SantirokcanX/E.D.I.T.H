"""Episodic error learning and continuous self-correction system for EDITH."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


class ErrorLearner:
    """Registra errores, extrae lecciones aprendidas y las inyecta en razonamientos futuros."""

    def __init__(self, storage_path: Optional[str] = None):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.storage_dir = Path(storage_path) if storage_path else base_dir / "data" / "learnings"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.storage_dir / "error_learnings.json"
        self.learnings: List[Dict[str, Any]] = self._load_learnings()

    def _load_learnings(self) -> List[Dict[str, Any]]:
        if not self.file_path.exists():
            # Crear archivo base con lecciones de arranque
            initial_learnings = [
                {
                    "id": "init_1",
                    "task": "Búsqueda web",
                    "error": "Búsquedas con términos excesivamente largos o específicos devuelven listas vacías.",
                    "lesson": "Al buscar en internet, utilizar palabras clave concisas y entidades directas, evitando oraciones completas con signos de puntuación.",
                    "timestamp": datetime.now().isoformat()
                },
                {
                    "id": "init_2",
                    "task": "Lectura de páginas web",
                    "error": "Intentar leer URLs no válidas o de servicios con bloqueo agresivo de bots.",
                    "lesson": "Verificar que el enlace comience con http:// o https:// y descartar URLs rotas o que requieran inicio de sesión obligatorio.",
                    "timestamp": datetime.now().isoformat()
                }
            ]
            self._save_to_disk(initial_learnings)
            return initial_learnings
        
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_to_disk(self, data: Optional[List[Dict[str, Any]]] = None):
        if data is None:
            data = self.learnings
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ErrorLearner] Error guardando lecciones: {e}")

    def record_error(self, task: str, error_desc: str, lesson_learned: str) -> Dict[str, Any]:
        """Registra un nuevo error y la heurística de aprendizaje derivada."""
        entry = {
            "id": f"err_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "task": task,
            "error": error_desc,
            "lesson": lesson_learned,
            "timestamp": datetime.now().isoformat()
        }
        self.learnings.append(entry)
        self._save_to_disk()
        return entry

    def get_all_lessons(self) -> List[str]:
        """Devuelve todas las lecciones aprendidas formateadas."""
        return [f"- {item.get('lesson')}" for item in self.learnings if item.get("lesson")]

    def _select_lessons(self, query: str, limit: int) -> List[Dict[str, Any]]:
        """Prioriza las lecciones más relevantes a la consulta (ML) y completa con las recientes."""
        recent = self.learnings[-limit:]
        if not query or len(self.learnings) <= limit:
            return recent
        try:
            from ..ml import MLEngine
            texts = [f"{l.get('task', '')} {l.get('error', '')} {l.get('lesson', '')}" for l in self.learnings]
            idx = MLEngine.rank(query, texts, k=limit, min_score=0.12)
        except Exception:
            return recent
        chosen = [self.learnings[i] for i in idx]
        for item in reversed(self.learnings):  # completar con las más recientes
            if len(chosen) >= limit:
                break
            if item not in chosen:
                chosen.append(item)
        return chosen

    def get_contextual_rules(self, query: str = "", limit: int = 5) -> str:
        """Genera una directiva para el prompt del sistema con las reglas aprendidas."""
        if not self.learnings:
            return ""

        selected = self._select_lessons(query, limit)
        rules = [f"• {item.get('lesson')} (Contexto: {item.get('task')})" for item in selected]
        
        return (
            "\n[EXPERIENCIA Y LECCIONES APRENDIDAS DE ERRORES PREVIOS]:\n"
            "Como EDITH, has aprendido de interacciones previas. Aplica rigurosamente estas reglas:\n"
            + "\n".join(rules)
            + "\n"
        )


_global_error_learner: Optional[ErrorLearner] = None

def get_error_learner() -> ErrorLearner:
    global _global_error_learner
    if _global_error_learner is None:
        _global_error_learner = ErrorLearner()
    return _global_error_learner
