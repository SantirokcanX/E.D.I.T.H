"""Aviso de versión nueva (Fase 15.5).

La app instalada consulta una vez al día el último *release* del repositorio de EDITH en GitHub
(UPDATE_REPO) y, si es más nuevo que el archivo VERSION, la interfaz ofrece descargar su
EDITH-Setup.exe. Instalarlo encima reemplaza solo el programa: conversaciones, memoria y ajustes
viven en %LOCALAPPDATA%\\EDITH y se conservan. Se desactiva en Ajustes › Avanzado (UPDATE_CHECK).
"""

import json
import re
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import httpx

from .config import Config
from .paths import EDITH_HOME, FROZEN, VERSION

UPDATE_FILE = EDITH_HOME / "update.json"
CHECK_EVERY_SECONDS = 24 * 3600


def parse_version(text: str) -> Tuple[int, ...]:
    """'v0.1.2' -> (0, 1, 2). Lo que no sea número cuenta como 0."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def _load() -> Dict[str, Any]:
    try:
        return json.loads(UPDATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: Dict[str, Any]):
    try:
        UPDATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def state() -> Dict[str, Any]:
    s = _load()
    s["current"] = VERSION
    s["enabled"] = Config.UPDATE_CHECK
    if s.get("latest"):
        s["newer"] = parse_version(s["latest"]) > parse_version(VERSION)  # por si se actualizó desde la última consulta
    return s


def check(force: bool = False) -> Dict[str, Any]:
    if not Config.UPDATE_CHECK:
        return state()
    cached = _load()
    if not force and time.time() - float(cached.get("checked_ts", 0)) < CHECK_EVERY_SECONDS:
        return state()
    result: Dict[str, Any] = {"checked_at": datetime.now().isoformat(timespec="seconds"), "checked_ts": time.time()}
    try:
        r = httpx.get(f"https://api.github.com/repos/{Config.UPDATE_REPO}/releases/latest", timeout=6.0,
                      headers={"Accept": "application/vnd.github+json", "User-Agent": f"EDITH/{VERSION}"},
                      follow_redirects=True)
        if r.status_code == 404:
            result.update(latest=None, newer=False)  # aún no hay releases publicados
        else:
            r.raise_for_status()
            rel = r.json()
            tag = rel.get("tag_name") or rel.get("name") or ""
            setup = next((a.get("browser_download_url") for a in rel.get("assets", [])
                          if re.match(r"(?i)^EDITH-Setup.*\.exe$", a.get("name", ""))), None)
            result.update(latest=tag.lstrip("vV"), newer=parse_version(tag) > parse_version(VERSION),
                          url=rel.get("html_url"), setup_url=setup, notes=(rel.get("body") or "")[:600])
    except Exception as e:
        result.update(error=f"{type(e).__name__}")
        result["checked_ts"] = time.time() - CHECK_EVERY_SECONDS + 3600  # sin internet: reintentar en 1 h
        result.update({k: cached[k] for k in ("latest", "newer", "url", "setup_url", "notes") if k in cached})
    _save(result)
    return state()


def start_background_check(delay: float = 30.0) -> Optional[threading.Thread]:
    """Solo en la app instalada (desde el código se actualiza con git)."""
    if not (FROZEN and Config.UPDATE_CHECK):
        return None

    def run():
        time.sleep(delay)
        while True:
            check()
            time.sleep(CHECK_EVERY_SECONDS)
    t = threading.Thread(target=run, name="edith-updates", daemon=True)
    t.start()
    return t
