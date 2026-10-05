"""Comprehensive Tools package for EDITH: Web, Workspace, System Control, and Visual Diagrams."""

from .web_search import web_search, read_web_page, TOOLS_METADATA as SEARCH_TOOLS_METADATA
from .workspace_tools import (
    save_to_workspace,
    read_workspace_file,
    list_workspace_files,
    WORKSPACE_TOOLS_METADATA,
    WORKSPACE_DIR
)
from .system_tools import (
    open_application,
    get_system_status,
    run_system_command,
    control_system_volume,
    SYSTEM_TOOLS_METADATA
)
from .diagram_tools import save_diagram, DIAGRAM_TOOLS_METADATA
from .screen_tools import (
    capture_screen,
    analyze_screen,
    get_active_window_info
)

SCREEN_TOOLS_METADATA = [
    {
        "name": "capture_screen",
        "description": "Toma una captura de pantalla instantánea de la laptop y la almacena en el workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "enum": ["full", "active_window"],
                    "description": "Área a capturar ('full' o 'active_window')."
                }
            },
            "required": []
        }
    },
    {
        "name": "analyze_screen",
        "description": "Toma una captura de la pantalla de la laptop y la analiza visualmente para responder preguntas sobre lo que el usuario está viendo (código, errores, ventanas, diseños).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pregunta o instrucción específica sobre lo que hay en pantalla."
                }
            },
            "required": []
        }
    }
]

ALL_TOOLS_METADATA = (
    SEARCH_TOOLS_METADATA +
    WORKSPACE_TOOLS_METADATA +
    SYSTEM_TOOLS_METADATA +
    DIAGRAM_TOOLS_METADATA +
    SCREEN_TOOLS_METADATA
)

__all__ = [
    "web_search",
    "read_web_page",
    "save_to_workspace",
    "read_workspace_file",
    "list_workspace_files",
    "open_application",
    "get_system_status",
    "run_system_command",
    "control_system_volume",
    "save_diagram",
    "capture_screen",
    "analyze_screen",
    "get_active_window_info",
    "SEARCH_TOOLS_METADATA",
    "WORKSPACE_TOOLS_METADATA",
    "SYSTEM_TOOLS_METADATA",
    "DIAGRAM_TOOLS_METADATA",
    "SCREEN_TOOLS_METADATA",
    "ALL_TOOLS_METADATA",
    "WORKSPACE_DIR"
]
