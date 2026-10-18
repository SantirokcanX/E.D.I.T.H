"""Workspace file collaboration tools for human-agent and multi-agent co-working."""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..paths import WORKSPACE_DIR
WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)


def get_workspace_path(filename: str) -> Path:
    """Resuelve la ruta segura dentro del directorio workspace."""
    clean_name = filename.strip("/\\")
    root = WORKSPACE_DIR.resolve()
    resolved = (root / clean_name).resolve()
    # Protección de traversal: comparar por componentes de ruta, no por prefijo de texto
    # (con startswith, "../workspace_x/archivo" se colaba porque "workspace_x" empieza por "workspace")
    if resolved != root and root not in resolved.parents:
        raise ValueError("Acceso denegado: intento de salida del directorio workspace.")
    return resolved


def save_to_workspace(filename: str, content: str) -> str:
    """
    Guarda o sobrescribe un archivo en el espacio de trabajo compartido 'workspace/'.
    Útil para generar informes, análisis, código fuente o notas de trabajo conjunto.
    """
    try:
        path = get_workspace_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        msg = f"Archivo guardado exitosamente en workspace: '{filename}' ({len(content)} caracteres)."
        if path.name.lower() == "notas_del_dia.md":
            try:
                from .obsidian_tools import mirror_daily_notes
                note = mirror_daily_notes(content)
                if note:
                    msg += f" También quedó en Obsidian: {note}."
            except Exception as e:  # la bóveda nunca debe impedir guardar en el workspace
                msg += f" (No se pudo copiar a Obsidian: {e})"
        return msg
    except Exception as e:
        return f"Error al guardar archivo en workspace: {str(e)}"


READ_CHUNK = 12_000  # caracteres por lectura: el modelo local tiene poco contexto


def read_workspace_file(filename: str, offset: int = 0) -> str:
    """
    Lee el contenido de un archivo del espacio de trabajo compartido 'workspace/'.
    Los archivos largos se leen por partes: offset = desde qué carácter.
    """
    try:
        path = get_workspace_path(filename)
        if not path.exists():
            return f"El archivo '{filename}' no existe en el workspace."
        if not path.is_file():
            return f"'{filename}' es un directorio, no un archivo legible."
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        offset = max(0, int(offset or 0))
        part = text[offset:offset + READ_CHUNK]
        if offset + READ_CHUNK < len(text):
            part += (f"\n… (sigue: {len(text) - offset - READ_CHUNK} caracteres más; vuelve a leer con "
                     f"offset={offset + READ_CHUNK})")
        return part
    except Exception as e:
        return f"Error al leer archivo de workspace: {str(e)}"


def list_workspace_files() -> List[Dict[str, Any]]:
    """
    Lista todos los archivos y subdirectorios dentro del espacio de trabajo compartido 'workspace/'.
    """
    try:
        results = []
        for p in WORKSPACE_DIR.rglob("*"):
            rel = p.relative_to(WORKSPACE_DIR)
            results.append({
                "path": str(rel).replace("\\", "/"),
                "is_dir": p.is_dir(),
                "size_bytes": p.stat().st_size if p.is_file() else 0
            })
        return results
    except Exception as e:
        return [{"error": f"Error listando archivos: {str(e)}"}]


WORKSPACE_TOOLS_METADATA = [
    {
        "name": "save_to_workspace",
        "description": "Crea o actualiza un archivo (documento, reporte, script o código) en la carpeta compartida 'workspace/' para que el usuario o el equipo pueda verlo y editarlo.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nombre relativo del archivo (ej. 'resumen_analisis.md', 'scout_report.txt', 'main.py')."
                },
                "content": {
                    "type": "string",
                    "description": "Contenido textual completo a guardar en el archivo."
                }
            },
            "required": ["filename", "content"]
        }
    },
    {
        "name": "read_workspace_file",
        "description": "Lee el contenido de un archivo existente en la carpeta compartida 'workspace/'.",
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Nombre del archivo a leer."
                },
                "offset": {
                    "type": "integer",
                    "description": "Opcional: desde qué carácter seguir leyendo un archivo largo."
                }
            },
            "required": ["filename"]
        }
    },
    {
        "name": "list_workspace_files",
        "description": "Muestra la lista de todos los archivos y carpetas presentes en el espacio de trabajo compartido 'workspace/'.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]
