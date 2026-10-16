"""Recordatorios y alarmas de EDITH (Fase 11).

EDITH los crea cuando se lo pides ("recuérdame mañana a las 9 llamar al dentista") y el
Heartbeat los dispara a su hora por los canales configurados (interfaz, Windows, WhatsApp).
Los críticos esperan confirmación: si no respondes, el Heartbeat escala a una llamada.
"""

import json
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..paths import DATA_DIR

REMINDERS_FILE = DATA_DIR / "reminders.json"
_lock = threading.RLock()

REPEATS = ("none", "daily", "weekly")
_WEEKDAYS = {"lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3, "viernes": 4, "sabado": 5, "domingo": 6}
# "viernes 07:30", "mañana a las 9", "pasado mañana 6 pm", "hoy 18:00", "el lunes"
_NATURAL = re.compile(
    r"^(?:el\s+)?(?P<day>hoy|pasado\s+manana|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)"
    r"(?:\s+(?:a\s+las?\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm|a\.m\.|p\.m\.)?)?"
    r"(?:\s+de\s+la\s+(?P<part>manana|tarde|noche))?$")
_REL = re.compile(r"^\s*(?:\+|en\s+|in\s+)?(\d+)\s*(m|min|minutos?|h|horas?|d|d[ií]as?)\s*$", re.IGNORECASE)


def _load() -> List[Dict[str, Any]]:
    try:
        return json.loads(REMINDERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    REMINDERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = REMINDERS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REMINDERS_FILE)


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _parse_natural(text: str, now: datetime) -> Optional[datetime]:
    m = _NATURAL.match(re.sub(r"\s+", " ", _strip_accents(text.lower())).strip())
    if not m:
        return None
    day = m.group("day")
    hour = int(m.group("h")) if m.group("h") else 9
    minute = int(m.group("m")) if m.group("m") else 0
    ampm = (m.group("ampm") or "").replace(".", "")
    part = m.group("part")
    if (ampm == "pm" or part in ("tarde", "noche")) and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    base = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day == "hoy":
        return base
    if day == "manana":
        return base + timedelta(days=1)
    if day.startswith("pasado"):
        return base + timedelta(days=2)
    ahead = (_WEEKDAYS[day] - now.weekday()) % 7
    if ahead == 0 and base <= now:
        ahead = 7  # "el jueves" dicho un jueves después de esa hora = el de la próxima semana
    return base + timedelta(days=ahead)


def parse_when(when: str, now: Optional[datetime] = None) -> datetime:
    """Acepta relativo ('+10m', 'en 2 horas'), natural ('viernes 07:30', 'mañana 9 am',
    'pasado mañana 6 pm') o ISO ('2026-10-16T09:00'). El calendario lo resuelve el código,
    no el modelo: los modelos pequeños se equivocan contando días."""
    now = now or datetime.now()
    text = (when or "").strip()
    natural = _parse_natural(text, now)
    if natural:
        return natural
    m = _REL.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        if unit.startswith("m"):
            return now + timedelta(minutes=n)
        if unit.startswith("h"):
            return now + timedelta(hours=n)
        return now + timedelta(days=n)
    try:
        dt = datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        raise ValueError(
            f"No entiendo la fecha '{when}'. Usa '+30m'/'+2h'/'+1d', 'mañana 09:00', 'viernes 07:30' o 'AAAA-MM-DDTHH:MM'."
        )
    return dt.replace(tzinfo=None)


def _public(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in ("id", "text", "due", "critical", "repeat", "status")}


def create_reminder(text: str, when: str, critical: bool = False, repeat: str = "none") -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"error": "El recordatorio necesita un texto."}
    try:
        due = parse_when(when)
    except ValueError as e:
        return {"error": str(e)}
    if due < datetime.now() - timedelta(minutes=1):
        return {"error": f"La fecha {due:%Y-%m-%d %H:%M} ya pasó. Pide la fecha correcta."}
    repeat = repeat if repeat in REPEATS else "none"
    item = {
        "id": uuid.uuid4().hex[:6],
        "text": text[:300],
        "due": due.isoformat(timespec="minutes"),
        "critical": bool(critical),
        "repeat": repeat,
        "status": "pending",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    with _lock:
        items = _load()
        items.append(item)
        _save(items)
    return {**_public(item), "result": "creado"}


def list_reminders(include_done: bool = False) -> List[Dict[str, Any]]:
    with _lock:
        items = _load()
    active = ("pending", "fired")
    shown = [r for r in items if include_done or r.get("status") in active]
    shown.sort(key=lambda r: r.get("due", ""))
    return [_public(r) for r in shown]


def cancel_reminder(reminder_id: str) -> Dict[str, Any]:
    with _lock:
        items = _load()
        for r in items:
            if r["id"] == reminder_id and r["status"] in ("pending", "fired"):
                r["status"] = "cancelled"
                _save(items)
                return {**_public(r), "result": "cancelado"}
    return {"error": f"No hay un recordatorio activo con id '{reminder_id}'."}


def ack_reminder(reminder_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Confirma un recordatorio crítico disparado (el más reciente si no se indica id)."""
    with _lock:
        items = _load()
        waiting = [r for r in items if r["status"] == "fired" and r.get("critical")
                   and (reminder_id is None or r["id"] == reminder_id)]
        if not waiting:
            return None
        r = max(waiting, key=lambda x: x.get("fired_at", ""))
        r["status"] = "acked"
        r["acked_at"] = datetime.now().isoformat(timespec="seconds")
        _save(items)
        return _public(r)


def take_due(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Devuelve los recordatorios que ya tocan y los marca como disparados.
    Los repetitivos programan su siguiente ocurrencia."""
    now = now or datetime.now()
    fired = []
    with _lock:
        items = _load()
        new_items = []
        for r in items:
            if r["status"] != "pending" or datetime.fromisoformat(r["due"]) > now:
                continue
            r["status"] = "fired" if r.get("critical") else "done"
            r["fired_at"] = now.isoformat(timespec="seconds")
            fired.append(dict(r))
            if r.get("repeat") in ("daily", "weekly"):
                step = timedelta(days=1 if r["repeat"] == "daily" else 7)
                nxt = datetime.fromisoformat(r["due"]) + step
                while nxt <= now:
                    nxt += step
                new_items.append({**r, "id": uuid.uuid4().hex[:6], "due": nxt.isoformat(timespec="minutes"),
                                  "status": "pending", "fired_at": None, "escalated": False})
        if fired:
            _save(items + new_items)
    return fired


def awaiting_escalation(minutes: int, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Críticos disparados hace más de `minutes` sin confirmar ni escalar; los marca como escalados."""
    now = now or datetime.now()
    out = []
    with _lock:
        items = _load()
        for r in items:
            if (r["status"] == "fired" and r.get("critical") and not r.get("escalated")
                    and r.get("fired_at") and now - datetime.fromisoformat(r["fired_at"]) >= timedelta(minutes=minutes)):
                r["escalated"] = True
                out.append(dict(r))
        if out:
            _save(items)
    return out


def due_today(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now()
    today = now.date().isoformat()
    return [r for r in list_reminders() if r["due"].startswith(today)]


REMINDER_TOOLS_METADATA = [
    {
        "name": "create_reminder",
        "description": "Crea un recordatorio o alarma. EDITH avisará a esa hora por la interfaz, Windows y WhatsApp. "
                       "Usa la fecha y hora actual del contexto para calcular 'mañana', 'en 2 horas', etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Qué hay que recordar."},
                "when": {"type": "string", "description": "Cuándo, tal como lo diría el usuario: 'en X tiempo' -> '+30m', '+2h', '+1d'; "
                                                           "día de la semana o mañana -> 'viernes 07:30', 'mañana 09:00', 'hoy 18:00' (24 h). "
                                                           "Solo para fechas lejanas usa 'AAAA-MM-DDTHH:MM'."},
                "critical": {"type": "boolean", "description": "true si es urgente: si no se confirma, EDITH escala a una llamada telefónica."},
                "repeat": {"type": "string", "enum": list(REPEATS), "description": "Repetición: none, daily o weekly."}
            },
            "required": ["text", "when"]
        }
    },
    {
        "name": "list_reminders",
        "description": "Lista los recordatorios activos (pendientes o esperando confirmación). Úsala SIEMPRE que pregunten qué recordatorios hay.",
        "parameters": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "cancel_reminder",
        "description": "Cancela un recordatorio por su id (obtén el id con list_reminders).",
        "parameters": {
            "type": "object",
            "properties": {"reminder_id": {"type": "string", "description": "Id del recordatorio."}},
            "required": ["reminder_id"]
        }
    }
]
