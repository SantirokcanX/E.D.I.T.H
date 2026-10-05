"""Base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]
    id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "arguments": self.arguments,
            "id": self.id
        }


@dataclass
class AgentStepResponse:
    thought: str = ""
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    
    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLMProvider(ABC):
    """Interfaz base para proveedores de modelos de lenguaje."""
    
    @abstractmethod
    def generate_step(
        self,
        messages: List[Dict[str, Any]],
        tools_metadata: List[Dict[str, Any]],
        on_thought_chunk: Optional[Callable[[str], None]] = None,
        on_content_chunk: Optional[Callable[[str], None]] = None
    ) -> AgentStepResponse:
        """
        Ejecuta un paso de inferencia del LLM.
        
        Args:
            messages: Historial de mensajes (usuario, asistente, sistema, herramientas).
            tools_metadata: Lista de definiciones de herramientas disponibles.
            on_thought_chunk: Callback opcional invocado al recibir tokens de razonamiento.
            on_content_chunk: Callback opcional invocado al recibir tokens de respuesta.
            
        Returns:
            AgentStepResponse con el razonamiento, contenido y llamadas a herramientas (si las hay).
        """
        pass

    @abstractmethod
    def is_available(self) -> tuple[bool, str]:
        """
        Verifica si el proveedor está listo y disponible (servicio activo, credenciales válidas).
        
        Returns:
            (disponible: bool, mensaje: str)
        """
        pass
