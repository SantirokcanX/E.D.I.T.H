"""Notificaciones proactivas de EDITH: interfaz, Windows (toast), WhatsApp y llamada.

Respeta las horas de silencio (QUIET_HOURS): de noche solo pasan los avisos críticos.
"""

import asyncio
import os
import subprocess
import sys
import threading
from datetime import datetime, time as dtime, timedelta
from typing import Any, Callable, Dict, List, Optional

from ..config import Config
from ..paths import APP_DIR

# Identidad de EDITH en Windows: la barra de tareas y las notificaciones la muestran como
# "EDITH" con su logo (sin esto, los avisos aparecen como "Windows PowerShell").
APP_USER_MODEL_ID = "EDITH.Desktop"
_POWERSHELL_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_aumid_ready: Optional[bool] = None

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

# Toast nativo de Windows sin dependencias (WinRT desde PowerShell 5.1).
# Título y mensaje viajan por variables de entorno: nunca se interpolan en el script.
_TOAST_PS = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$texts = $xml.GetElementsByTagName('text')
$null = $texts.Item(0).AppendChild($xml.CreateTextNode($env:EDITH_TOAST_TITLE))
$null = $texts.Item(1).AppendChild($xml.CreateTextNode($env:EDITH_TOAST_BODY))
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:EDITH_TOAST_APPID).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def _parse_hhmm(s: str) -> Optional[dtime]:
    try:
        h, m = s.strip().split(":")
        return dtime(int(h), int(m))
    except Exception:
        return None


def in_quiet_hours(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    try:
        start_s, end_s = Config.QUIET_HOURS.split("-")
    except ValueError:
        return False
    start, end = _parse_hhmm(start_s), _parse_hhmm(end_s)
    if not start or not end:
        return False
    t = now.time()
    return (start <= t or t < end) if start > end else (start <= t < end)


def register_app_identity() -> bool:
    """Registra EDITH como remitente de notificaciones del usuario actual (HKCU, sin admin)."""
    global _aumid_ready
    if _aumid_ready is not None:
        return _aumid_ready
    _aumid_ready = False
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key_path = rf"Software\Classes\AppUserModelId\{APP_USER_MODEL_ID}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "EDITH")
            icon = APP_DIR / "desktop" / "assets" / "edith-tray.png"
            if icon.exists():
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon))
            winreg.SetValueEx(key, "IconBackgroundColor", 0, winreg.REG_SZ, "FF0A0A0F")
        _aumid_ready = True
    except OSError:
        pass
    return _aumid_ready


def _run_toast(app_id: str, title: str, body: str) -> bool:
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", _TOAST_PS], timeout=15,
                          creationflags=_NO_WINDOW, capture_output=True,
                          env={**os.environ, "EDITH_TOAST_TITLE": title[:120], "EDITH_TOAST_BODY": body[:300],
                               "EDITH_TOAST_APPID": app_id})
    return proc.returncode == 0


def show_toast(title: str, body: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        if register_app_identity() and _run_toast(APP_USER_MODEL_ID, title, body):
            return True
        return _run_toast(_POWERSHELL_APP_ID, title, body)  # respaldo: como antes
    except Exception:
        return False


class Notifier:
    def __init__(self):
        self._ui_broadcast: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.paused_until: Optional[datetime] = None

    # ---------- pausa (menú de la bandeja: "Pausar avisos 1 h") ----------
    def pause(self, minutes: int = 60):
        self.paused_until = datetime.now() + timedelta(minutes=minutes)

    def resume(self):
        self.paused_until = None

    @property
    def paused(self) -> bool:
        if self.paused_until and datetime.now() >= self.paused_until:
            self.paused_until = None
        return self.paused_until is not None

    def register_ui(self, broadcast: Callable[[Dict[str, Any]], Any], loop: asyncio.AbstractEventLoop):
        """`broadcast` es una corrutina del servidor que envía el evento a todas las pestañas abiertas."""
        self._ui_broadcast, self._loop = broadcast, loop

    def notify(self, title: str, message: str, level: str = "info", reminder_id: Optional[str] = None,
               channels: Optional[List[str]] = None, whatsapp_text: Optional[str] = None) -> Dict[str, bool]:
        """Envía un aviso por los canales configurados. level: info | warning | critical."""
        channels = channels or Config.NOTIFY_CHANNELS
        # De noche o en pausa, lo no crítico solo queda en la interfaz
        quiet = (in_quiet_hours() or self.paused) and level != "critical"
        event = {"type": "notification", "title": title, "message": message, "level": level,
                 "reminder_id": reminder_id, "at": datetime.now().isoformat(timespec="seconds")}
        with self._lock:
            self.history = (self.history + [event])[-50:]
        sent: Dict[str, bool] = {}

        if "ui" in channels and self._ui_broadcast and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(self._ui_broadcast(event), self._loop)
                sent["ui"] = True
            except Exception:
                sent["ui"] = False
        if quiet:
            return sent  # de noche, lo no crítico solo queda en la interfaz
        if "toast" in channels:
            sent["toast"] = show_toast(f"EDITH · {title}", message)
        if "whatsapp" in channels and Config.WHATSAPP_ENABLED:
            from .whatsapp import send_whatsapp
            icon = {"critical": "🚨", "warning": "⚠️"}.get(level, "🔔")
            text = whatsapp_text or f"{icon} *{title}*\n{message}"
            if level == "critical" and reminder_id:
                text += "\n\n_Responde *ok* para confirmar o te llamo._"
            sent["whatsapp"] = send_whatsapp(text)
        return sent

    def toast_if_enabled(self, title: str, message: str) -> bool:
        """Solo la notificación de Windows, y solo si está activada en «Avisar por» (Fase 6)."""
        if "toast" not in Config.NOTIFY_CHANNELS:
            return False
        return bool(self.notify(title, message, channels=["toast"]).get("toast"))

    def call(self, message: str, reminder_id: Optional[str] = None) -> Dict[str, Any]:
        from .telephony import make_call
        return make_call(message, reminder_id=reminder_id)


notifier = Notifier()
