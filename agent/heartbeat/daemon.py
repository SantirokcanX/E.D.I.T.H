"""Heartbeat Daemon (Fase 11): EDITH deja de ser solo reactiva.

Cada minuto:          dispara recordatorios que ya tocan y escala alarmas críticas sin confirmar.
Cada HEARTBEAT_MINUTES: revisa la salud de la laptop y las tareas con fecha de Obsidian.
Una vez al día:       resumen matutino (recordatorios, tareas, laptop y noticias opcionales),
                      enviado por los canales y guardado en "01 - Diario/" de la bóveda.

El estado (qué ya se avisó) se guarda en data/heartbeat_state.json para no repetir avisos
aunque EDITH se reinicie.
"""

import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..channels.notifier import Notifier, _parse_hhmm
from ..config import Config
from ..core.concurrency import LLM_LOCK
from ..tools import reminder_tools

from ..paths import DATA_DIR

STATE_FILE = DATA_DIR / "heartbeat_state.json"

# Tareas de Obsidian con fecha: "- [ ] Entregar informe 📅 2026-10-16", "due:: 2026-10-16" o "@2026-10-16"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
         "octubre", "noviembre", "diciembre"]
TASK_RE = re.compile(r"^\s*[-*+]\s+\[ \]\s+(?P<text>.+)$")
DATE_RE = re.compile(r"(?:📅|⏳|due::|@)\s*(\d{4}-\d{2}-\d{2})")


class Heartbeat:
    def __init__(self, provider, notifier: Notifier):
        self.provider = provider
        self.notifier = notifier
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.state = self._load_state()
        self.last_run: Optional[str] = None

    # ---------- ciclo ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="edith-heartbeat", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f"[Heartbeat] error: {e}")
            self._stop.wait(60)

    def tick(self, now: Optional[datetime] = None, force_full: bool = False, force_briefing: bool = False) -> Dict[str, Any]:
        """Un latido. Devuelve qué hizo (útil para pruebas y para /api/heartbeat/run)."""
        now = now or datetime.now()
        report: Dict[str, Any] = {"at": now.isoformat(timespec="seconds")}
        report["reminders"] = self._fire_reminders(now)
        report["escalated"] = self._escalate(now)

        last_full = self.state.get("last_full_check")
        due_full = force_full or not last_full or (
            now - datetime.fromisoformat(last_full) >= timedelta(minutes=Config.HEARTBEAT_MINUTES))
        if due_full:
            report["system"] = self._check_system()
            report["tasks"] = self._check_obsidian_tasks(now)
            self.state["last_full_check"] = now.isoformat(timespec="seconds")

        if force_briefing or self._briefing_due(now):
            report["briefing"] = self.morning_briefing(now)

        self.last_run = report["at"]
        self._save_state()
        return report

    # ---------- recordatorios ----------
    def _fire_reminders(self, now: datetime) -> List[str]:
        fired = reminder_tools.take_due(now)
        for r in fired:
            level = "critical" if r.get("critical") else "info"
            self.notifier.notify("Recordatorio", r["text"], level=level, reminder_id=r["id"])
        return [r["text"] for r in fired]

    def _escalate(self, now: datetime) -> List[str]:
        out = []
        for r in reminder_tools.awaiting_escalation(Config.ESCALATE_AFTER_MINUTES, now):
            result = self.notifier.call(f"Recordatorio urgente: {r['text']}", reminder_id=r["id"])
            if "error" in result:
                # Sin teléfono configurado: insistir por los demás canales
                self.notifier.notify("Recordatorio sin confirmar", r["text"], level="critical", reminder_id=r["id"])
            out.append(r["text"])
        return out

    # ---------- salud de la laptop ----------
    def _check_system(self) -> Dict[str, Any]:
        import psutil
        alerts = []
        battery = psutil.sensors_battery()
        if battery is not None:
            low = battery.percent <= 20 and not battery.power_plugged
            if low and not self.state.get("battery_alerted"):
                self.notifier.notify("Batería baja", f"Queda {battery.percent:.0f}% y no está conectada al cargador.",
                                     level="warning")
                alerts.append("battery")
            self.state["battery_alerted"] = low
        cpu = psutil.cpu_percent(interval=1)
        streak = self.state.get("cpu_high_streak", 0) + 1 if cpu >= 90 else 0
        self.state["cpu_high_streak"] = streak
        if streak == 3:  # uso alto sostenido durante 3 revisiones seguidas
            self.notifier.notify("CPU al máximo", f"La CPU lleva un buen rato por encima del 90% ({cpu:.0f}% ahora).",
                                 level="warning")
            alerts.append("cpu")
        disk = psutil.disk_usage("C:\\" if Path("C:\\").exists() else "/")
        disk_low = disk.free / disk.total < 0.10
        if disk_low and self.state.get("disk_alert_date") != date.today().isoformat():
            self.notifier.notify("Disco casi lleno", f"Quedan {disk.free / 1024**3:.1f} GB libres.", level="warning")
            self.state["disk_alert_date"] = date.today().isoformat()
            alerts.append("disk")
        return {"cpu": cpu, "battery": getattr(battery, "percent", None), "alerts": alerts}

    # ---------- tareas de Obsidian ----------
    def obsidian_tasks(self, now: datetime) -> Dict[str, List[str]]:
        from ..tools.obsidian_tools import get_vault_path
        vault = get_vault_path()
        today = now.date().isoformat()
        out: Dict[str, List[str]] = {"today": [], "overdue": []}
        if not vault.exists():
            return out
        for p in vault.rglob("*.md"):
            if ".obsidian" in p.parts or ".trash" in p.parts:
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                m = TASK_RE.match(line)
                if not m:
                    continue
                d = DATE_RE.search(line)
                if not d:
                    continue
                text = DATE_RE.sub("", m.group("text")).strip()
                entry = f"{text} ({p.stem})"
                if d.group(1) == today:
                    out["today"].append(entry)
                elif d.group(1) < today:
                    out["overdue"].append(entry)
        return out

    def _check_obsidian_tasks(self, now: datetime) -> Dict[str, List[str]]:
        tasks = self.obsidian_tasks(now)
        today = now.date().isoformat()
        notified = self.state.get("tasks_notified", {})
        if notified.get("date") != today:
            notified = {"date": today, "items": []}
        new = [t for t in tasks["today"] + tasks["overdue"] if t not in notified["items"]]
        # El resumen matutino ya las lista: aquí solo se avisa de las que aparezcan después
        if new and self.state.get("last_briefing_date") == today:
            self.notifier.notify("Tareas para hoy", "\n".join(f"• {t}" for t in new[:8]), level="info")
        notified["items"] += new
        self.state["tasks_notified"] = notified
        return tasks

    # ---------- resumen matutino ----------
    def _briefing_due(self, now: datetime) -> bool:
        at = _parse_hhmm(Config.MORNING_BRIEFING_TIME) if Config.MORNING_BRIEFING_TIME else None
        if not at or self.state.get("last_briefing_date") == now.date().isoformat():
            return False
        start = datetime.combine(now.date(), at)
        if now < start:
            return False
        if now - start > timedelta(hours=3):
            # EDITH arrancó mucho después de la hora: un "resumen matutino" a media tarde no tiene sentido
            self.state["last_briefing_date"] = now.date().isoformat()
            return False
        return True

    def _news(self) -> List[str]:
        if not Config.HEARTBEAT_NEWS_TOPICS:
            return []
        from ..tools.web_search import web_search
        headlines = []
        for topic in Config.HEARTBEAT_NEWS_TOPICS[:3]:
            try:
                for r in web_search(query=f"{topic} noticias hoy", max_results=2):
                    if isinstance(r, dict) and r.get("title"):
                        headlines.append(f"{topic}: {r['title']}")
            except Exception:
                continue
        return headlines

    def morning_briefing(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        import psutil
        now = now or datetime.now()
        reminders = reminder_tools.due_today(now)
        tasks = self.obsidian_tasks(now)
        battery = psutil.sensors_battery()
        news = self._news()
        facts = {
            "fecha": f"{DIAS[now.weekday()]} {now.day} de {MESES[now.month - 1]} de {now.year}",
            "recordatorios_hoy": [f"{r['due'][11:16]} {r['text']}" for r in reminders],
            "tareas_hoy": tasks["today"],
            "tareas_vencidas": tasks["overdue"],
            "bateria": f"{battery.percent:.0f}%" if battery else "N/A",
            "noticias": news,
        }
        text = self._write_briefing(facts)
        self.state["last_briefing_date"] = now.date().isoformat()
        self.notifier.notify("Resumen matutino", text, level="info",
                             whatsapp_text=f"☀️ *Resumen matutino*\n\n{text}")
        note = None
        try:
            from ..tools.obsidian_tools import _note_path, create_note, get_vault_path
            title = f"{now:%Y-%m-%d} - Resumen matutino"
            existing = _note_path(title, "01 - Diario")
            if existing.exists():
                # Otra EDITH (p. ej. la de la laptop y la del servidor) ya lo escribió hoy: no se pisa
                note = str(existing.relative_to(get_vault_path())).replace("\\", "/")
            else:
                note = create_note(title, text, folder="01 - Diario",
                                   tags=["edith", "resumen-matutino"]).get("note")
        except Exception as e:
            print(f"[Heartbeat] no se pudo guardar el resumen en Obsidian: {e}")
        return {"text": text, "note": note, "facts": facts}

    def _write_briefing(self, facts: Dict[str, Any]) -> str:
        """Redacta el resumen con el modelo rápido; si falla, usa una plantilla."""
        prompt = (
            "Redacta el resumen matutino para el usuario con estos datos (JSON). En español, cálido y breve "
            "(máximo 8 líneas), empieza con un saludo de buenos días, menciona primero lo urgente y no inventes "
            "nada que no esté en los datos. Sin LaTeX ni tablas.\n\n" + json.dumps(facts, ensure_ascii=False)
        )
        try:
            with LLM_LOCK:
                resp = self.provider.generate_step(
                    messages=[{"role": "system", "content": "Eres E.D.I.T.H., la asistente personal del usuario."},
                              {"role": "user", "content": prompt}],
                    tools_metadata=[], think=False)
            if resp.content.strip():
                return resp.content.strip()
        except Exception as e:
            print(f"[Heartbeat] resumen con plantilla (el modelo falló: {e})")
        lines = [f"Buenos días. Hoy es {facts['fecha']}."]
        if facts["recordatorios_hoy"]:
            lines.append("Recordatorios: " + "; ".join(facts["recordatorios_hoy"]))
        if facts["tareas_vencidas"]:
            lines.append("Tareas vencidas: " + "; ".join(facts["tareas_vencidas"][:5]))
        if facts["tareas_hoy"]:
            lines.append("Para hoy: " + "; ".join(facts["tareas_hoy"][:5]))
        if facts["noticias"]:
            lines.append("Titulares: " + "; ".join(facts["noticias"][:4]))
        lines.append(f"Batería de la laptop: {facts['bateria']}.")
        return "\n".join(lines)

    # ---------- estado ----------
    def _load_state(self) -> Dict[str, Any]:
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": Config.HEARTBEAT_ENABLED,
            "running": bool(self._thread and self._thread.is_alive()),
            "every_minutes": Config.HEARTBEAT_MINUTES,
            "morning_briefing": Config.MORNING_BRIEFING_TIME or None,
            "quiet_hours": Config.QUIET_HOURS,
            "last_run": self.last_run,
            "last_briefing_date": self.state.get("last_briefing_date"),
        }
