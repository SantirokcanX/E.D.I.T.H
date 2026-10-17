"""Correo de solo lectura por IMAP (Fase 11).

Se configura en Ajustes › Casa y cuentas: servidor IMAP, tu correo y una **contraseña de aplicación**
(Gmail: Cuenta de Google › Seguridad › Contraseñas de aplicaciones; se guarda cifrada con DPAPI).
EDITH abre el buzón en modo solo lectura (EXAMINE): no marca nada como leído, no borra ni envía.
"""

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List, Optional

from ..config import Config

MAX_BODY = 4000


def enabled() -> bool:
    return bool(Config.EMAIL_IMAP_HOST and Config.EMAIL_ADDRESS and Config.EMAIL_PASSWORD)


def _connect():
    conn = imaplib.IMAP4_SSL(Config.EMAIL_IMAP_HOST, Config.EMAIL_IMAP_PORT, timeout=20)
    conn.login(Config.EMAIL_ADDRESS, Config.EMAIL_PASSWORD)
    status, _ = conn.select("INBOX", readonly=True)  # EXAMINE: nada cambia en el servidor
    if status != "OK":
        raise imaplib.IMAP4.error("no pude abrir la bandeja de entrada")
    return conn


def _h(value: Optional[str]) -> str:
    try:
        return str(make_header(decode_header(value or ""))).strip()
    except Exception:
        return (value or "").strip()


def _error(e: Exception) -> Dict[str, str]:
    if isinstance(e, imaplib.IMAP4.error) and "auth" in str(e).lower():
        return {"error": "El servidor de correo rechazó el acceso: usa una contraseña de aplicación (Ajustes › Casa y cuentas)."}
    return {"error": f"No pude leer el correo ({type(e).__name__}: {str(e)[:120]})."}


def _text_of(msg: email.message.Message) -> str:
    parts = msg.walk() if msg.is_multipart() else [msg]
    plain, html = "", ""
    for part in parts:
        if part.get_content_maintype() == "multipart" or part.get("Content-Disposition", "").startswith("attachment"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and not plain:
            plain = text
        elif part.get_content_type() == "text/html" and not html:
            html = text
    if not plain and html:
        plain = unescape(re.sub(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", " ", html, flags=re.DOTALL | re.IGNORECASE))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", plain)).strip()


def email_list(unread_only: bool = True, max_results: int = 10, search: str = "") -> Dict[str, Any]:
    if not enabled():
        return {"error": "El correo no está configurado (Ajustes › Casa y cuentas)."}
    max_results = max(1, min(int(max_results or 10), 30))
    try:
        conn = _connect()
        try:
            criteria: List[str] = ["UNSEEN"] if unread_only else ["ALL"]
            if search:
                safe = search.replace('"', "").replace("\\", "")[:80]
                criteria += ["OR", "SUBJECT", f'"{safe}"', "FROM", f'"{safe}"']
            status, data = conn.uid("SEARCH", "CHARSET", "UTF-8", *criteria) if search else conn.uid("SEARCH", *criteria)
            uids = (data[0] or b"").split()[-max_results:][::-1]
            out = []
            for uid in uids:
                st, fetched = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                raw = next((p[1] for p in fetched if isinstance(p, tuple)), b"")
                h = email.message_from_bytes(raw)
                try:
                    when = parsedate_to_datetime(h.get("Date")).astimezone().strftime("%Y-%m-%d %H:%M")
                except Exception:
                    when = h.get("Date", "")
                out.append({"uid": uid.decode(), "from": _h(h.get("From")), "subject": _h(h.get("Subject")) or "(sin asunto)",
                            "date": when})
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        return _error(e)
    return {"messages": out, "count": len(out), "unread_only": bool(unread_only)}


def email_read(uid: str) -> Dict[str, Any]:
    if not enabled():
        return {"error": "El correo no está configurado (Ajustes › Casa y cuentas)."}
    if not str(uid).isdigit():
        return {"error": "Indica el número (uid) del correo, de email_list."}
    try:
        conn = _connect()
        try:
            st, fetched = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")  # PEEK: no lo marca como leído
            raw = next((p[1] for p in fetched if isinstance(p, tuple)), None)
            if not raw:
                return {"error": "No encontré ese correo."}
            msg = email.message_from_bytes(raw)
        finally:
            try:
                conn.logout()
            except Exception:
                pass
    except Exception as e:
        return _error(e)
    body = _text_of(msg)
    attachments = [_h(p.get_filename()) for p in msg.walk() if p.get_filename()]
    return {"uid": str(uid), "from": _h(msg.get("From")), "subject": _h(msg.get("Subject")), "date": msg.get("Date", ""),
            "body": body[:MAX_BODY] + ("…" if len(body) > MAX_BODY else ""), "attachments": attachments}


def unread_summary(limit: int = 3) -> Dict[str, Any]:
    """Para el resumen matutino: cuántos sin leer y los asuntos de los últimos."""
    r = email_list(unread_only=True, max_results=limit)
    if "error" in r:
        return {}
    return {"sin_leer": r["count"], "ultimos": [f"{m['subject']} — {m['from']}" for m in r["messages"]]}


EMAIL_HANDLERS = {"email_list": email_list, "email_read": email_read}
EMAIL_TOOLS_METADATA = [
    {"name": "email_list",
     "description": "Lista correos de la bandeja de entrada del usuario (por defecto los no leídos). Solo lectura.",
     "parameters": {"type": "object", "properties": {
         "unread_only": {"type": "boolean"}, "max_results": {"type": "integer"},
         "search": {"type": "string", "description": "Opcional: texto en el asunto o remitente."}}}},
    {"name": "email_read", "description": "Lee un correo por su uid (de email_list). No lo marca como leído.",
     "parameters": {"type": "object", "properties": {"uid": {"type": "string"}}, "required": ["uid"]}},
]
