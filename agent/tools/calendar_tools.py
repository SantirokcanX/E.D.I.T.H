"""Calendario (Fase 11): tus eventos desde el enlace iCal de Google Calendar u Outlook.

Se configura en Ajustes › Casa y cuentas con la «dirección secreta en formato iCal» (Google:
Configuración del calendario › Integrar calendario; Outlook: Compartir › Publicar calendario › ICS).
Es de solo lectura y ese enlace se guarda cifrado (quien lo tenga puede ver tu calendario).
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from ..config import Config

_cache: Dict[str, Any] = {"at": None, "events": None, "key": None}
CACHE_SECONDS = 300


def enabled() -> bool:
    return bool(Config.CALENDAR_ICS_URLS)


def _fetch(url: str) -> bytes:
    if url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    r = httpx.get(url, timeout=20.0, follow_redirects=True)
    r.raise_for_status()
    return r.content


def _as_local(value) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    return datetime.combine(value, datetime.min.time())


def events_between(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    import icalendar
    import recurring_ical_events

    out: List[Dict[str, Any]] = []
    for url in Config.CALENDAR_ICS_URLS:
        cal = icalendar.Calendar.from_ical(_fetch(url))
        for ev in recurring_ical_events.of(cal).between(start, end):
            dtstart = ev.get("DTSTART").dt
            dtend = ev.get("DTEND").dt if ev.get("DTEND") else dtstart
            all_day = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
            out.append({
                "title": str(ev.get("SUMMARY", "(sin título)")),
                "start": _as_local(dtstart).isoformat(timespec="minutes"),
                "end": _as_local(dtend).isoformat(timespec="minutes"),
                "all_day": all_day,
                "location": str(ev.get("LOCATION", "")) or None,
            })
    out.sort(key=lambda e: e["start"])
    return out


def calendar_events(days: int = 7, start_date: str = "") -> Dict[str, Any]:
    if not enabled():
        return {"error": "No hay calendario configurado (Ajustes › Casa y cuentas › enlace iCal)."}
    try:
        start = datetime.fromisoformat(start_date) if start_date else datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        return {"error": "Fecha no válida: usa AAAA-MM-DD."}
    days = max(1, min(int(days or 7), 60))
    end = start + timedelta(days=days)
    key = (tuple(Config.CALENDAR_ICS_URLS), start.isoformat(), days)
    now = datetime.now()
    if _cache["key"] == key and _cache["at"] and (now - _cache["at"]).total_seconds() < CACHE_SECONDS:
        events = _cache["events"]
    else:
        try:
            events = events_between(start, end)
        except Exception as e:
            return {"error": f"No pude leer el calendario ({type(e).__name__}). Revisa el enlace iCal en Ajustes."}
        _cache.update(at=now, events=events, key=key)
    return {"from": start.date().isoformat(), "days": days, "events": events[:80], "count": len(events)}


def today_agenda(now: Optional[datetime] = None) -> List[str]:
    """Para el resumen matutino: '09:00 Junta de equipo (Oficina)'."""
    if not enabled():
        return []
    now = now or datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        events = events_between(start, start + timedelta(days=1))
    except Exception:
        return []
    return [("Todo el día" if e["all_day"] else e["start"][11:16]) + f" {e['title']}"
            + (f" ({e['location']})" if e.get("location") else "") for e in events]


CALENDAR_HANDLERS = {"calendar_events": calendar_events}
CALENDAR_TOOLS_METADATA = [
    {"name": "calendar_events",
     "description": "Consulta los eventos del calendario del usuario (citas, juntas, cumpleaños) en los próximos días.",
     "parameters": {"type": "object", "properties": {
         "days": {"type": "integer", "description": "Cuántos días mirar (1-60, por defecto 7)."},
         "start_date": {"type": "string", "description": "Opcional: desde qué fecha (AAAA-MM-DD). Por defecto hoy."}}}},
]
