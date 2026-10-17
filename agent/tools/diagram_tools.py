"""Diagramming and conceptual visual tools for EDITH."""

from pathlib import Path
from typing import Dict, Any, List
from .workspace_tools import save_to_workspace


def save_diagram(title: str, diagram_type: str, code: str) -> str:
    """
    Guarda un diagrama, mapa conceptual o gráfica en el workspace para visualización y exportación.
    
    Args:
        title: Título o nombre descriptivo del diagrama (ej. 'mapa_conceptual_ia', 'flujo_proyecto').
        diagram_type: Tipo de diagrama ('mermaid', 'chartjs', 'svg').
        code: El código fuente del diagrama (código Mermaid, configuración Chart.js o SVG).
    """
    clean_title = title.lower().replace(" ", "_").strip()
    
    if diagram_type == "mermaid":
        filename = f"{clean_title}.mmd"
    elif diagram_type == "chartjs":
        filename = f"{clean_title}_chart.json"
    elif diagram_type == "svg":
        filename = f"{clean_title}.svg"
    else:
        filename = f"{clean_title}.txt"

    res = save_to_workspace(filename, code)
    msg = f"Diagrama guardado en workspace como '{filename}'. Se renderiza automáticamente en la pestaña de Diagramas."
    try:
        from .obsidian_tools import mirror_diagram
        note = mirror_diagram(title, diagram_type, code)
        if note:
            msg += f" También quedó en Obsidian: {note}."
    except Exception as e:  # la bóveda nunca debe impedir guardar el diagrama
        msg += f" (No se pudo copiar a Obsidian: {e})"
    return msg


DIAGRAM_TOOLS_METADATA = [
    {
        "name": "save_diagram",
        "description": "Guarda un diagrama de flujo, mapa conceptual o gráfica en el workspace ('workspace/'). EDITH puede generar diagramas Mermaid (mindmap, flowchart, etc.) o SVG para ilustrar conceptos visualmente.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Nombre del diagrama (ej. 'mapa_arquitectura', 'flujo_decisiones')."
                },
                "diagram_type": {
                    "type": "string",
                    "enum": ["mermaid", "chartjs", "svg"],
                    "description": "El formato o tipo de diagrama."
                },
                "code": {
                    "type": "string",
                    "description": "El código fuente completo del diagrama (sintaxis Mermaid como mindmap o flowchart, o código SVG)."
                }
            },
            "required": ["title", "diagram_type", "code"]
        }
    }
]
