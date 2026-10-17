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
from .obsidian_tools import (
    create_note as obsidian_create_note,
    append_note as obsidian_append_note,
    read_note as obsidian_read_note,
    search_vault as obsidian_search,
    sync_edith_session as obsidian_sync_session,
    list_notes as obsidian_list_notes,
    create_obsidian_note,
    append_to_obsidian_note,
    read_obsidian_note,
    list_obsidian_notes,
    OBSIDIAN_TOOLS_METADATA
)
from .clipboard_tools import read_clipboard, write_clipboard, CLIPBOARD_TOOLS_METADATA
from .reminder_tools import create_reminder, list_reminders, cancel_reminder, REMINDER_TOOLS_METADATA
from .keyboard_tools import keyboard_actions, KEYBOARD_TOOLS_METADATA
from .browser_tools import BROWSER_HANDLERS, BROWSER_TOOLS_METADATA, browser_active
from . import calendar_tools, email_tools, home_tools
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
    SCREEN_TOOLS_METADATA +
    OBSIDIAN_TOOLS_METADATA +
    CLIPBOARD_TOOLS_METADATA +
    REMINDER_TOOLS_METADATA +
    KEYBOARD_TOOLS_METADATA +
    [t for t in BROWSER_TOOLS_METADATA if t["name"] == "browser_open"]
)

# Grupos opcionales: solo se ofrecen al modelo si están configurados (Home Assistant, correo...).
# Cada módulo añade (función_que_dice_si_está_activo, metadatos).
OPTIONAL_TOOL_GROUPS = [
    # El resto del navegador solo cuando hay una página abierta: así no gasta contexto del modelo
    (browser_active, [t for t in BROWSER_TOOLS_METADATA if t["name"] != "browser_open"]),
    (home_tools.enabled, home_tools.HOME_TOOLS_METADATA),
    (calendar_tools.enabled, calendar_tools.CALENDAR_TOOLS_METADATA),
    (email_tools.enabled, email_tools.EMAIL_TOOLS_METADATA),
]


def available_tools_metadata():
    tools = list(ALL_TOOLS_METADATA)
    for enabled, metadata in OPTIONAL_TOOL_GROUPS:
        try:
            if enabled():
                tools.extend(metadata)
        except Exception:
            pass
    return tools


# Herramientas nuevas: nombre -> función(**args). ReasoningAgent las ejecuta sin tocar su lista de casos.
EXTRA_HANDLERS = {
    "keyboard_actions": keyboard_actions,
    **BROWSER_HANDLERS,
    **home_tools.HOME_HANDLERS,
    **calendar_tools.CALENDAR_HANDLERS,
    **email_tools.EMAIL_HANDLERS,
}

# Herramientas que tocan la máquina directamente: bloqueadas desde canales remotos
# (WhatsApp, teléfono) salvo REMOTE_ALLOW_SYSTEM_TOOLS=true.
LOCAL_ONLY_TOOLS = {
    "run_system_command", "open_application", "control_system_volume",
    "capture_screen", "analyze_screen", "read_clipboard", "write_clipboard",
    "keyboard_actions", "browser_show",
}

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
    "obsidian_create_note",
    "obsidian_append_note",
    "obsidian_read_note",
    "obsidian_search",
    "obsidian_sync_session",
    "obsidian_list_notes",
    "create_obsidian_note",
    "append_to_obsidian_note",
    "read_obsidian_note",
    "list_obsidian_notes",
    "read_clipboard",
    "write_clipboard",
    "create_reminder",
    "list_reminders",
    "cancel_reminder",
    "REMINDER_TOOLS_METADATA",
    "LOCAL_ONLY_TOOLS",
    "EXTRA_HANDLERS",
    "OPTIONAL_TOOL_GROUPS",
    "available_tools_metadata",
    "keyboard_actions",
    "OBSIDIAN_TOOLS_METADATA",
    "CLIPBOARD_TOOLS_METADATA",
    "SEARCH_TOOLS_METADATA",
    "WORKSPACE_TOOLS_METADATA",
    "SYSTEM_TOOLS_METADATA",
    "DIAGRAM_TOOLS_METADATA",
    "SCREEN_TOOLS_METADATA",
    "ALL_TOOLS_METADATA",
    "WORKSPACE_DIR"
]
