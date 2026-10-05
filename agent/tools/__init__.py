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

ALL_TOOLS_METADATA = (
    SEARCH_TOOLS_METADATA +
    WORKSPACE_TOOLS_METADATA +
    SYSTEM_TOOLS_METADATA +
    DIAGRAM_TOOLS_METADATA
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
    "SEARCH_TOOLS_METADATA",
    "WORKSPACE_TOOLS_METADATA",
    "SYSTEM_TOOLS_METADATA",
    "DIAGRAM_TOOLS_METADATA",
    "ALL_TOOLS_METADATA",
    "WORKSPACE_DIR"
]
