"""Obsidian vault tools: EDITH's external memory and tactical notebook (Fase 2).

Trabaja directamente sobre los archivos .md de la bóveda, así que funciona aunque
Obsidian esté cerrado y no necesita ningún plugin. Si el plugin "Local REST API" está
activo en la bóveda, además empuja cada cambio a Obsidian en caliente.
"""

import json
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..config import Config

VAULT_FOLDERS = [
    "00 - Dashboard",
    "01 - Diario",
    "02 - Proyectos",
    "03 - Conocimiento",
    "04 - Memoria EDITH",
]
DIARY_FOLDER = "01 - Diario"

_api_down_until = 0.0  # pausa los reintentos al plugin Local REST API si Obsidian está cerrado

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def get_vault_path() -> Path:
    return Path(Config.OBSIDIAN_VAULT_PATH).expanduser().resolve()


def ensure_vault_structure() -> Path:
    """Crea la estructura de carpetas recomendada si aún no existe."""
    vault = get_vault_path()
    for folder in VAULT_FOLDERS:
        (vault / folder).mkdir(parents=True, exist_ok=True)
    return vault


def _api_credentials() -> Tuple[Optional[str], int]:
    """Clave y puerto HTTP del plugin Local REST API de la bóveda (si está configurado)."""
    cfg = get_vault_path() / ".obsidian" / "plugins" / "obsidian-local-rest-api" / "data.json"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 27123
    if not data.get("enableInsecureServer", True):
        return None, 27123
    return data.get("apiKey"), int(data.get("insecurePort", 27123))


def _push_to_obsidian(path: Path, text: str) -> bool:
    """Sincronización en caliente con Obsidian abierto (mejor esfuerzo, nunca bloquea)."""
    global _api_down_until
    if time.monotonic() < _api_down_until:
        return False
    api_key, port = _api_credentials()
    if not api_key:
        return False
    rel = str(path.relative_to(get_vault_path())).replace("\\", "/")
    url = f"http://127.0.0.1:{port}/vault/{urllib.parse.quote(rel)}"
    try:
        res = httpx.put(url, content=text.encode("utf-8"), timeout=httpx.Timeout(1.5, connect=0.3),
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "text/markdown"})
        return res.status_code in (200, 204)
    except Exception:
        # Obsidian cerrado: no volver a esperar la conexión en cada escritura
        _api_down_until = time.monotonic() + 30
        return False


def _write_note(path: Path, text: str) -> bool:
    """Escribe la nota en disco y la empuja a Obsidian si está abierto. Devuelve si hubo sync en vivo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return _push_to_obsidian(path, text)


def _safe_name(title: str) -> str:
    name = _INVALID_CHARS.sub("", title).strip().strip(".")
    return name[:120] or "Nota sin título"


def _resolve(relative: str) -> Path:
    """Ruta dentro de la bóveda; impide escapar de ella con '..'."""
    vault = get_vault_path()
    target = (vault / relative).resolve()
    if vault != target and vault not in target.parents:
        raise ValueError("Ruta fuera de la bóveda de Obsidian")
    return target


def _note_path(title: str, folder: str = "") -> Path:
    if title.lower().endswith(".md"):
        title = title[:-3]
    parts = [_safe_name(p) for p in re.split(r"[\\/]", folder or "") if p.strip(" .")]
    return _resolve("/".join(parts + [_safe_name(title) + ".md"]))


def _find_note(title: str) -> Optional[Path]:
    """Busca una nota por título en toda la bóveda (como hacen los [[wikilinks]])."""
    vault = get_vault_path()
    direct = _note_path(title)
    if direct.exists():
        return direct
    wanted = _safe_name(title[:-3] if title.lower().endswith(".md") else title).lower()
    for p in vault.rglob("*.md"):
        if ".obsidian" in p.parts or ".trash" in p.parts:
            continue
        if p.stem.lower() == wanted:
            return p
    return None


def _frontmatter(tags: List[str]) -> str:
    lines = ["---", f"created: {datetime.now().strftime('%Y-%m-%d %H:%M')}", "source: EDITH"]
    if tags:
        lines.append("tags:")
        lines.extend(f"  - {t.lstrip('#').strip()}" for t in tags if t.strip())
    lines.append("---\n")
    return "\n".join(lines)


def create_note(title: str, content: str, folder: str = "", tags: Optional[List[str]] = None,
                overwrite: bool = False) -> Dict[str, Any]:
    """Crea una nota en la bóveda. Si ya existe y overwrite=False, añade el contenido al final."""
    vault = ensure_vault_structure()
    path = _note_path(title, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        return _append_to(path, content)
    if isinstance(tags, str):
        tags = [t for t in re.split(r"[,\s]+", tags) if t]
    body = content if content.lstrip().startswith("---") else _frontmatter(tags or ["edith"]) + content
    live = _write_note(path, body.rstrip() + "\n")
    return {"status": "creada", "note": str(path.relative_to(vault)).replace("\\", "/"), "api_synced": live}


def append_note(title: str, content: str) -> Dict[str, Any]:
    """Añade contenido al final de una nota existente (o la crea en la raíz si no existe)."""
    ensure_vault_structure()
    path = _find_note(title)
    if path is None:
        return create_note(title, content)
    return _append_to(path, content)


def _append_to(path: Path, content: str) -> Dict[str, Any]:
    vault = get_vault_path()
    existing = path.read_text(encoding="utf-8")
    sep = "" if existing.endswith("\n") else "\n"
    live = _write_note(path, existing + sep + "\n" + content.rstrip() + "\n")
    return {"status": "actualizada", "note": str(path.relative_to(vault)).replace("\\", "/"), "api_synced": live}


def read_note(title: str) -> Dict[str, Any]:
    vault = get_vault_path()
    path = _find_note(title)
    if path is None:
        return {"error": f"No encontré la nota '{title}' en la bóveda."}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"note": str(path.relative_to(vault)).replace("\\", "/"), "content": text[:12000]}


def list_notes(folder: str = "") -> List[Dict[str, Any]]:
    """Lista las notas de la bóveda (o de una carpeta), las más recientes primero."""
    vault = get_vault_path()
    base = _resolve("/".join(_safe_name(p) for p in re.split(r"[\\/]", folder or "") if p.strip(" ."))) if folder else vault
    if not base.exists():
        return []
    notes = []
    for p in base.rglob("*.md"):
        if ".obsidian" in p.parts or ".trash" in p.parts:
            continue
        st = p.stat()
        notes.append({"name": p.stem, "path": str(p.relative_to(vault)).replace("\\", "/"),
                      "size": st.st_size, "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")})
    notes.sort(key=lambda n: n["modified"], reverse=True)
    return notes[:200]


# --- Compatibilidad con la primera versión de la integración (nombres de herramienta antiguos) ---
def create_obsidian_note(filename: str, content: str, folder: str = "") -> Dict[str, Any]:
    """Versión anterior: crea o SOBRESCRIBE la nota."""
    return create_note(filename, content, folder=folder, overwrite=True)


def append_to_obsidian_note(filename: str, content: str, folder: str = "") -> Dict[str, Any]:
    path = _note_path(filename, folder)
    if path.exists():
        ensure_vault_structure()
        return _append_to(path, content)
    return append_note(filename, content) if not folder else create_note(filename, content, folder=folder)


def read_obsidian_note(filename: str, folder: str = "") -> Dict[str, Any]:
    path = _note_path(filename, folder)
    if folder and path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")
        return {"note": str(path.relative_to(get_vault_path())).replace("\\", "/"), "content": text[:12000]}
    return read_note(filename)


def list_obsidian_notes(folder: str = "") -> List[Dict[str, Any]]:
    return list_notes(folder)


def search_vault(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    """Búsqueda de texto en la bóveda: coincidencias en título pesan más que en contenido."""
    vault = get_vault_path()
    if not vault.exists():
        return []
    terms = [t for t in query.lower().split() if len(t) > 1]
    if not terms:
        return []
    results = []
    for p in vault.rglob("*.md"):
        if ".obsidian" in p.parts or ".trash" in p.parts:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        low, title = text.lower(), p.stem.lower()
        score = sum(3 * (t in title) + min(low.count(t), 5) for t in terms)
        if score == 0:
            continue
        idx = min((low.find(t) for t in terms if t in low), default=0)
        snippet = text[max(0, idx - 80): idx + 200].replace("\n", " ").strip()
        results.append({"note": str(p.relative_to(vault)).replace("\\", "/"),
                        "score": score, "snippet": snippet})
    results.sort(key=lambda r: -r["score"])
    return results[:max_results]


DIAGRAMS_FOLDER = "03 - Conocimiento/Diagramas"


def _vault_ready() -> Optional[Path]:
    """La bóveda solo si existe y la copia está activada: nunca se crea una bóveda que no tienes."""
    if not Config.OBSIDIAN_SAVE_WORKSPACE:
        return None
    vault = get_vault_path()
    return vault if vault.is_dir() else None


def mirror_daily_notes(content: str) -> Optional[str]:
    """Fase 2: workspace/notas_del_dia.md -> 01 - Diario/AAAA-MM-DD - Notas del día.md (se reescribe)."""
    vault = _vault_ready()
    if not vault:
        return None
    title = f"{datetime.now().strftime('%Y-%m-%d')} - Notas del día"
    path = _note_path(title, DIARY_FOLDER)
    body = content if content.lstrip().startswith("---") else _frontmatter(["edith", "notas-del-dia"]) + content
    _write_note(path, body.rstrip() + "\n")
    return str(path.relative_to(vault)).replace("\\", "/")


def mirror_diagram(title: str, diagram_type: str, code: str) -> Optional[str]:
    """Fase 2: cada diagrama también como nota en 03 - Conocimiento/Diagramas (Obsidian dibuja Mermaid)."""
    vault = _vault_ready()
    if not vault:
        return None
    name = _safe_name(title.replace("_", " ").strip() or "Diagrama")
    path = _note_path(name, DIAGRAMS_FOLDER)
    head = _frontmatter(["edith", "diagrama"]) + f"# {name}\n\n"
    if diagram_type == "mermaid":
        body = head + f"```mermaid\n{code.strip()}\n```\n"
    elif diagram_type == "svg":
        svg = path.with_suffix(".svg")
        svg.parent.mkdir(parents=True, exist_ok=True)
        svg.write_text(code, encoding="utf-8")
        body = head + f"![[{svg.name}]]\n"
    else:
        body = head + "Gráfica de Chart.js: ábrela en EDITH para verla.\n\n" + f"```json\n{code.strip()}\n```\n"
    _write_note(path, body)
    return str(path.relative_to(vault)).replace("\\", "/")


def session_to_markdown(session: Dict[str, Any]) -> str:
    """Convierte una sesión guardada de EDITH en una nota legible de Obsidian."""
    created = session.get("created_at", "")[:16].replace("T", " ")
    lines = [
        "---",
        f"edith_session: {session.get('id', '')}",
        f"created: {created}",
        f"updated: {session.get('updated_at', '')[:16].replace('T', ' ')}",
        "tags:",
        "  - edith",
        "  - conversacion",
        "---",
        "",
        f"# {session.get('title', 'Conversación con EDITH')}",
        "",
    ]
    for m in session.get("messages", []):
        role, content = m.get("role"), str(m.get("content", "")).strip()
        if role == "user" and content:
            lines += [f"**🧑 Tú:** {content}", ""]
        elif role == "assistant" and content:
            lines += [f"**👓 EDITH:**", "", content, ""]
        elif role == "tool":
            lines += [f"> [!note]- Herramienta `{m.get('name', '')}`", "> (resultado omitido)", ""]
    lines.append("---")
    lines.append("*Sincronizado desde E.D.I.T.H. — [[Plan de Cambios y Evolución de EDITH]]*")
    return "\n".join(lines)


def sync_edith_session(session_id: Optional[str] = None) -> Dict[str, Any]:
    """Guarda (o actualiza) una conversación de EDITH como nota en '01 - Diario/'."""
    from ..memory.memory_manager import get_memory_manager

    memory = get_memory_manager()
    sid = session_id or memory.current_session_id
    session = memory.get_session(sid)
    if not session:
        return {"error": f"No existe la sesión '{sid}'."}
    vault = ensure_vault_structure()
    day = (session.get("created_at") or datetime.now().isoformat())[:10]
    title = f"{day} - {_safe_name(session.get('title', 'Conversación'))[:60]}"
    path = _note_path(title, DIARY_FOLDER)
    # Si la charla ya se había sincronizado con otro título, reemplazar esa nota (no duplicar)
    marker = f"edith_session: {sid}\n"
    for old in (vault / DIARY_FOLDER).glob("*.md"):
        if old != path:
            try:
                if marker in old.read_text(encoding="utf-8", errors="replace")[:300]:
                    old.unlink()
            except OSError:
                pass
    _write_note(path, session_to_markdown(session) + "\n")
    return {"status": "sincronizada", "note": str(path.relative_to(vault)).replace("\\", "/")}


OBSIDIAN_TOOLS_METADATA = [
    {
        "name": "obsidian_create_note",
        "description": "Crea una nota en la bóveda de Obsidian del usuario (su memoria externa). Úsala para guardar ideas, resúmenes, planes o conocimiento con [[wikilinks]].",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título de la nota (sin .md)."},
                "content": {"type": "string", "description": "Contenido en Markdown."},
                "folder": {"type": "string", "description": "Carpeta opcional, p. ej. '02 - Proyectos' o '03 - Conocimiento'."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Etiquetas opcionales."}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "obsidian_append_note",
        "description": "Añade contenido al final de una nota existente de Obsidian (la busca por título en toda la bóveda).",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Título de la nota."},
                "content": {"type": "string", "description": "Texto Markdown a añadir."}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "obsidian_read_note",
        "description": "Lee el contenido de una nota de la bóveda de Obsidian por su título.",
        "parameters": {
            "type": "object",
            "properties": {"title": {"type": "string", "description": "Título de la nota."}},
            "required": ["title"]
        }
    },
    {
        "name": "obsidian_search",
        "description": "Busca texto en todas las notas de la bóveda de Obsidian del usuario y devuelve las más relevantes con un fragmento.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Palabras a buscar."}},
            "required": ["query"]
        }
    },
    {
        "name": "obsidian_list_notes",
        "description": "Lista las notas de la bóveda de Obsidian (opcionalmente de una carpeta), las más recientes primero.",
        "parameters": {
            "type": "object",
            "properties": {"folder": {"type": "string", "description": "Carpeta opcional, p. ej. '01 - Diario'."}},
            "required": []
        }
    },
    {
        "name": "obsidian_sync_session",
        "description": "Guarda la conversación actual con EDITH como nota en '01 - Diario/' de la bóveda de Obsidian.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
]
