"""Windows clipboard tools (Fase 5): "EDITH, explica lo que acabo de copiar"."""

import subprocess
import sys
from typing import Any, Dict

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0
MAX_CLIPBOARD_CHARS = 12000


def read_clipboard() -> Dict[str, Any]:
    """Devuelve el texto que el usuario tiene copiado (Ctrl+C)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"],
            capture_output=True, timeout=8, creationflags=_NO_WINDOW,
        )
        text = out.stdout.decode("utf-8", errors="replace").rstrip("\r\n")
    except Exception as e:
        return {"error": f"No pude leer el portapapeles: {e}"}
    if not text.strip():
        return {"content": "", "note": "El portapapeles está vacío o no contiene texto."}
    truncated = len(text) > MAX_CLIPBOARD_CHARS
    return {"content": text[:MAX_CLIPBOARD_CHARS], "chars": len(text), "truncated": truncated}


def write_clipboard(text: str) -> str:
    """Copia texto al portapapeles para que el usuario lo pegue con Ctrl+V."""
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::InputEncoding = [Text.Encoding]::UTF8; $t = [Console]::In.ReadToEnd(); Set-Clipboard -Value $t"],
            input=text.encode("utf-8"), timeout=8, creationflags=_NO_WINDOW, check=True,
        )
        return f"Copiado al portapapeles ({len(text)} caracteres). Ya puedes pegarlo con Ctrl+V."
    except Exception as e:
        return f"No pude escribir en el portapapeles: {e}"


CLIPBOARD_TOOLS_METADATA = [
    {
        "name": "read_clipboard",
        "description": "Lee el texto que el usuario copió (Ctrl+C). Úsala cuando diga 'lo que copié', 'esto que tengo copiado', etc.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "write_clipboard",
        "description": "Copia un texto al portapapeles de Windows para que el usuario lo pegue con Ctrl+V.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Texto a copiar."}},
            "required": ["text"]
        }
    }
]
