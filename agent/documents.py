"""Leer documentos que llegan por WhatsApp (Fase 9): PDF, Word (.docx) y texto plano."""

import io
import re
import zipfile
from html import unescape
from pathlib import Path
from typing import Dict, Optional

MAX_CHARS = 5000
TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".html", ".xml", ".yaml", ".yml", ".ini"}


def _pdf(data: bytes) -> Dict[str, object]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return {"error": "El PDF tiene contraseña: no puedo abrirlo."}
    pages = []
    for page in reader.pages[:40]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n\n".join(p.strip() for p in pages if p.strip())
    if not text:
        return {"error": "El PDF no tiene texto seleccionable (parece escaneado): mándame una foto y lo leo con visión."}
    return {"text": text, "pages": len(reader.pages)}


def _docx(data: bytes) -> Dict[str, object]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = unescape(re.sub(r"<[^>]+>", "", xml))
    return {"text": re.sub(r"\n\s*\n+", "\n\n", text).strip()}


def extract_text(data: bytes, filename: str = "", mime: str = "") -> Dict[str, object]:
    """{'text', 'pages'?, 'truncated'} o {'error'}."""
    ext = Path(filename or "").suffix.lower()
    try:
        if ext == ".pdf" or mime == "application/pdf":
            out = _pdf(data)
        elif ext == ".docx" or "wordprocessingml" in (mime or ""):
            out = _docx(data)
        elif ext in TEXT_EXT or (mime or "").startswith("text/"):
            out = {"text": data.decode("utf-8", errors="replace")}
        else:
            return {"error": f"Todavía no sé leer archivos {ext or mime or 'de ese tipo'}: mándamelo en PDF, Word o texto."}
    except Exception as e:
        return {"error": f"No pude leer el documento ({type(e).__name__})."}
    if "error" in out:
        return out
    text = str(out["text"])
    out["truncated"] = len(text) > MAX_CHARS
    out["text"] = text[:MAX_CHARS] + ("…" if out["truncated"] else "")
    return out


def safe_filename(name: Optional[str], default: str = "documento") -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip()).strip(" .")
    return clean[:120] or default
