"""Session persistence and long-term memory management for EDITH."""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


class MemoryManager:
    """Administra sesiones de conversación guardadas y memoria de perfil a largo plazo."""

    def __init__(self, data_dir: Optional[str] = None):
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.data_dir = Path(data_dir) if data_dir else base_dir / "data"
        self.sessions_dir = self.data_dir / "sessions"
        self.memory_dir = self.data_dir / "memory"
        
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        
        self.long_term_file = self.memory_dir / "long_term_profile.json"
        self.current_session_id = self._get_or_create_active_session_id()
        self.long_term_data = self._load_long_term_data()

    def _get_or_create_active_session_id(self) -> str:
        # Buscar la última sesión activa o generar una nueva
        sessions = self.list_sessions()
        if sessions:
            return sessions[0]["id"]
        return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _load_long_term_data(self) -> Dict[str, Any]:
        if not self.long_term_file.exists():
            default_data = {
                "user_name": "Usuario",
                "known_facts": [
                    "El usuario prefiere un agente llamado EDITH con razonamiento abstracto y sin censura.",
                    "El proyecto integra búsqueda en internet, co-working, voz neural e IDE Web."
                ],
                "topics_discussed": []
            }
            try:
                with open(self.long_term_file, "w", encoding="utf-8") as f:
                    json.dump(default_data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return default_data

        try:
            with open(self.long_term_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"user_name": "Usuario", "known_facts": [], "topics_discussed": []}

    def save_long_term_data(self):
        try:
            with open(self.long_term_file, "w", encoding="utf-8") as f:
                json.dump(self.long_term_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MemoryManager] Error guardando memoria a largo plazo: {e}")

    def add_known_fact(self, fact: str):
        if fact and fact not in self.long_term_data["known_facts"]:
            self.long_term_data["known_facts"].append(fact)
            self.save_long_term_data()

    def create_new_session(self, title: str = "Nueva conversación") -> str:
        """Crea una nueva sesión y la establece como la activa."""
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.current_session_id = session_id
        session_data = {
            "id": session_id,
            "title": title,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "messages": []
        }
        self._write_session(session_id, session_data)
        return session_id

    def _write_session(self, session_id: str, data: Dict[str, Any]):
        filepath = self.sessions_dir / f"{session_id}.json"
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[MemoryManager] Error guardando sesión {session_id}: {e}")

    def save_session_turn(self, messages: List[Dict[str, Any]], title_candidate: Optional[str] = None):
        """Guarda el estado actual de los mensajes en la sesión activa."""
        session_path = self.sessions_dir / f"{self.current_session_id}.json"
        
        # Filtrar o serializar mensajes limpios (evitar objetos no serializables)
        serializable_messages = []
        for m in messages:
            msg_copy = {"role": m.get("role"), "content": str(m.get("content", ""))}
            if "name" in m:
                msg_copy["name"] = m["name"]
            if "tool_calls" in m and m["tool_calls"]:
                tc_serialized = []
                for tc in m["tool_calls"]:
                    if hasattr(tc, "to_dict"):
                        tc_serialized.append(tc.to_dict())
                    elif isinstance(tc, dict):
                        tc_serialized.append(tc)
                    else:
                        tc_serialized.append({"name": getattr(tc, "name", ""), "arguments": getattr(tc, "arguments", {})})
                msg_copy["tool_calls"] = tc_serialized
            serializable_messages.append(msg_copy)

        title = "Conversación"
        created_at = datetime.now().isoformat()

        if session_path.exists():
            try:
                with open(session_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                    title = existing.get("title", title)
                    created_at = existing.get("created_at", created_at)
            except Exception:
                pass

        if title == "Conversación" and title_candidate:
            title = title_candidate[:45] + ("..." if len(title_candidate) > 45 else "")

        data = {
            "id": self.current_session_id,
            "title": title,
            "created_at": created_at,
            "updated_at": datetime.now().isoformat(),
            "messages": serializable_messages
        }
        self._write_session(self.current_session_id, data)

    def load_session(self, session_id: str) -> Optional[List[Dict[str, Any]]]:
        """Carga los mensajes de una sesión existente y la vuelve activa."""
        session_path = self.sessions_dir / f"{session_id}.json"
        if not session_path.exists():
            return None
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.current_session_id = session_id
                return data.get("messages", [])
        except Exception:
            return None

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Devuelve una lista ordenada de todas las sesiones registradas."""
        sessions = []
        for p in self.sessions_dir.glob("*.json"):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    sessions.append({
                        "id": data.get("id", p.stem),
                        "title": data.get("title", "Sin título"),
                        "updated_at": data.get("updated_at", ""),
                        "messages_count": len(data.get("messages", []))
                    })
            except Exception:
                continue

        # Ordenar por fecha de actualización descendente
        sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
        return sessions

    def get_long_term_context(self) -> str:
        """Construye un bloque de memoria a largo plazo para inyectar a EDITH."""
        facts = self.long_term_data.get("known_facts", [])
        if not facts:
            return ""

        context_lines = [f"- {fact}" for fact in facts]
        return (
            "\n[MEMORIA A LARGO PLAZO DE EDITH - SESIONES ANTERIORES]:\n"
            "Recuerdas la siguiente información acumulada de tus interacciones y del usuario:\n"
            + "\n".join(context_lines)
            + "\n"
        )


_global_memory_manager: Optional[MemoryManager] = None

def get_memory_manager() -> MemoryManager:
    global _global_memory_manager
    if _global_memory_manager is None:
        _global_memory_manager = MemoryManager()
    return _global_memory_manager
