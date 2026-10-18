"""Archivos adjuntos en el chat (0.1.2): 📎, arrastrar y soltar o pegar.

1. La interfaz sube los archivos a /api/files/upload: se guardan en workspace/adjuntos (nombre limpio,
   máximo 10 por mensaje y 50 MB cada uno).
2. La consulta lleva sus ids; prepare_attachments() los lee con agent/files.py (cualquier formato) y arma
   el texto para el modelo, marcado como dato no confiable. Ese texto va solo en este turno: al historial
   pasa una lista corta con dónde quedó cada archivo y su texto completo (adjuntos/<nombre>.txt).
"""

import asyncio
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Tuple

from fastapi import APIRouter, File, HTTPException, UploadFile

from agent import files as file_reader
from agent.core.safety import mark_untrusted
from agent.paths import WORKSPACE_DIR

router = APIRouter()
ATTACH_DIR = WORKSPACE_DIR / "adjuntos"
MAX_FILES = 10
MAX_BYTES = 50 * 1024 * 1024


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    return path


@router.post("/api/files/upload")
async def upload(files: List[UploadFile] = File(...)):
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Máximo {MAX_FILES} archivos por mensaje.")
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    saved = []
    for f in files:
        name = file_reader.safe_filename(f.filename)
        dest = _unique(ATTACH_DIR / f"{stamp}_{name}")
        size = 0
        with open(dest, "wb") as out:
            while True:
                chunk = await f.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail=f"«{name}» pasa de 50 MB.")
                out.write(chunk)
        saved.append({"id": f"adjuntos/{dest.name}", "name": name, "size": size})
    return {"files": saved}


def resolve_attachment(file_id: str) -> Path:
    """Solo archivos subidos a workspace/adjuntos (nada de ../ ni rutas propias)."""
    rel = str(file_id or "").replace("\\", "/")
    if not rel.startswith("adjuntos/"):
        raise ValueError("no es un adjunto")
    path = (WORKSPACE_DIR / rel).resolve()
    if path.parent != ATTACH_DIR.resolve() or not path.is_file():
        raise ValueError("adjunto no encontrado")
    return path


async def prepare_attachments(ids: List[str], question: str,
                              status: Callable[[str], Awaitable[Any]]) -> Tuple[str, str, List[str]]:
    """(texto para el modelo en este turno, nota corta para el historial, problemas)."""
    infos: List[Dict[str, Any]] = []
    problems: List[str] = []
    for file_id in list(ids)[:MAX_FILES]:
        try:
            path = resolve_attachment(file_id)
        except ValueError:
            problems.append(f"No encontré el adjunto «{Path(str(file_id)).name}».")
            continue
        shown = path.name.split("_", 2)[-1] if path.name[:8].isdigit() else path.name
        await status(f"📎 Leyendo «{shown}»…")
        data = await asyncio.to_thread(path.read_bytes)
        info = await asyncio.to_thread(file_reader.read_any, data, shown, "", question)
        if "error" in info:
            info = {"name": shown, "label": "no se pudo leer", "size": len(data), "text": "", "note": info["error"]}
        info["saved"] = f"adjuntos/{path.name}"
        if info.get("text"):
            txt = path.with_name(path.name + ".txt")
            await asyncio.to_thread(txt.write_text, info["text"], "utf-8")
            info["text_file"] = f"adjuntos/{txt.name}"
        infos.append(info)
    if not infos:
        return "", "", problems
    blocks = file_reader.describe_for_model(infos)
    # mark_untrusted ya avisa al modelo de que es dato; un aviso extra aquí lo hacía repetirlo en la respuesta
    prompt = ("[Archivos que adjuntó el usuario]\n\n"
              + "\n\n".join(mark_untrusted(f"archivo adjunto «{i['name']}»", b) for i, b in zip(infos, blocks)))
    history = "[Adjuntos: " + "; ".join(
        f"«{i['name']}» ({i.get('label', '')}) en workspace/{i.get('text_file') or i['saved']}" for i in infos) + "]"
    return prompt, history, problems
