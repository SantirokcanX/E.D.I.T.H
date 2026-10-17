"""Navegación web interactiva (Fase 12): EDITH maneja un Microsoft Edge propio con Playwright.

- Perfil aparte en %LOCALAPPDATA%\\EDITH\\browser (no toca tu Edge de siempre) y, por defecto,
  sin ventana. Con browser_show se ve la ventana (para iniciar sesión tú o mirar qué hace).
- Cada página se devuelve como texto + lista numerada de enlaces, botones y campos.
- Seguir enlaces, leer y rellenar campos no pide permiso; pulsar botones (enviar formularios,
  comprar...) y descargar archivos SÍ (Fase 14). Todo lo que se lee es dato no confiable.
- Nunca escribe contraseñas ni datos de tarjeta: esos campos los rellenas tú (browser_show).

Playwright exige usarse siempre desde el mismo hilo: un hilo propio atiende todas las órdenes.
"""

import atexit
import queue
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from ..config import Config
from ..paths import EDITH_HOME, WORKSPACE_DIR

PROFILE_DIR = EDITH_HOME / "browser"
DOWNLOADS_DIR = WORKSPACE_DIR / "descargas"
MAX_TEXT = 4000
MAX_ELEMENTS = 120
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
NAV_TIMEOUT_MS = 30_000
SENSITIVE_FIELD = re.compile(r"pass|contrase|clave|pin\b|cvv|cvc|card|tarjeta|iban|clabe|ssn|curp|token|otp|2fa",
                             re.IGNORECASE)

_SNAPSHOT_JS = """
(maxEls) => {
  const sel = 'a[href], button, input, select, textarea, [role=button], [role=link], [contenteditable=true]';
  document.querySelectorAll('[data-edith-id]').forEach(e => e.removeAttribute('data-edith-id'));
  const out = []; let n = 0;
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (!r.width || !r.height || st.visibility === 'hidden' || st.display === 'none' || el.type === 'hidden') continue;
    n += 1; el.setAttribute('data-edith-id', String(n));
    const lab = (el.labels && el.labels[0] && el.labels[0].innerText) || el.getAttribute('aria-label')
      || el.placeholder || el.innerText || el.value || el.title || el.name || '';
    out.push({ id: n, tag: el.tagName.toLowerCase(), type: (el.type || el.getAttribute('role') || '').toLowerCase(),
      text: lab.replace(/\\s+/g, ' ').trim().slice(0, 80), href: el.tagName === 'A' ? el.href : '',
      name: (el.name || el.id || ''), autocomplete: (el.getAttribute('autocomplete') || '') });
    if (n >= maxEls) break;
  }
  return out;
}
"""


class BrowserError(Exception):
    pass


class _BrowserWorker:
    """Hilo dueño de Playwright. call(fn) ejecuta fn(worker) allí y devuelve su resultado."""

    def __init__(self):
        self._q: "queue.Queue" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.pw = None
        self.ctx = None
        self.page = None
        self.headed = False
        self.elements: Dict[int, Dict[str, Any]] = {}
        self.last_url = ""

    def _loop(self):
        while True:
            fn, box, done = self._q.get()
            if fn is None:
                self._close()
                done.set()
                return
            try:
                box["result"] = fn(self)
            except Exception as e:  # se re-lanza en el hilo que pidió la orden
                box["error"] = e
            finally:
                done.set()

    def call(self, fn: Callable[["_BrowserWorker"], Any], timeout: float = 90.0) -> Any:
        with self._lock:
            if not (self._thread and self._thread.is_alive()):
                self._thread = threading.Thread(target=self._loop, name="edith-browser", daemon=True)
                self._thread.start()
        box: Dict[str, Any] = {}
        done = threading.Event()
        self._q.put((fn, box, done))
        if not done.wait(timeout):
            raise BrowserError("El navegador tardó demasiado en responder.")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    # ---- dentro del hilo del navegador
    def ensure_page(self, headed: Optional[bool] = None):
        want_headed = self.headed if headed is None else headed
        if self.ctx is not None and want_headed != self.headed:
            url = self.page.url if self.page else None
            self._close(keep_pw=True)
            self._launch(want_headed)
            if url and url.startswith("http"):
                self.page.goto(url, timeout=NAV_TIMEOUT_MS)
        elif self.ctx is None:
            self._launch(want_headed)
        if self.page is None or self.page.is_closed():
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self.page

    def _launch(self, headed: bool):
        if self.pw is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise BrowserError("Falta Playwright: instala las dependencias (pip install -r requirements.txt).")
            self.pw = sync_playwright().start()
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.ctx = self.pw.chromium.launch_persistent_context(
                str(PROFILE_DIR), channel=Config.BROWSER_CHANNEL or "msedge", headless=not headed,
                accept_downloads=True, downloads_path=str(DOWNLOADS_DIR), locale="es-MX",
                viewport={"width": 1280, "height": 900})
        except Exception as e:
            raise BrowserError(f"No pude abrir Microsoft Edge ({type(e).__name__}). ¿Está instalado?") from e
        self.headed = headed
        self.ctx.set_default_timeout(NAV_TIMEOUT_MS)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def _close(self, keep_pw: bool = False):
        try:
            if self.ctx is not None:
                self.ctx.close()
        except Exception:
            pass
        self.ctx = self.page = None
        self.elements = {}
        if not keep_pw and self.pw is not None:
            try:
                self.pw.stop()
            except Exception:
                pass
            self.pw = None

    def shutdown(self):
        if self._thread and self._thread.is_alive():
            done = threading.Event()
            self._q.put((None, {}, done))
            done.wait(15)


_worker = _BrowserWorker()
atexit.register(_worker.shutdown)


# ---------------------------------------------------------------- utilidades
def _kind(el: Dict[str, Any]) -> str:
    if el["tag"] == "a" and el.get("href") and not el["href"].lower().startswith("javascript:"):
        return "enlace"
    if el["tag"] in ("input", "textarea", "select") or el.get("type") == "contenteditable":
        if el["tag"] == "input" and el.get("type") in ("submit", "button", "reset", "image"):
            return "botón"
        if el["tag"] == "input" and el.get("type") in ("checkbox", "radio"):
            return "casilla"
        return "campo"
    return "botón"


def is_sensitive_field(el: Dict[str, Any]) -> bool:
    if el.get("type") == "password":
        return True
    auto = (el.get("autocomplete") or "").lower()
    if auto.startswith("cc-") or "password" in auto or auto == "one-time-code":
        return True
    return bool(SENSITIVE_FIELD.search(f"{el.get('name', '')} {el.get('text', '')}"))


def _snapshot(w: _BrowserWorker) -> Dict[str, Any]:
    page = w.page
    try:
        page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    els = page.evaluate(_SNAPSHOT_JS, MAX_ELEMENTS)
    w.elements = {e["id"]: e for e in els}
    w.last_url = page.url  # copia en texto: los objetos de Playwright no se tocan desde otros hilos
    try:
        text = page.inner_text("body", timeout=5_000)
    except Exception:
        text = ""
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    lines = []
    for e in els:
        k = _kind(e)
        extra = ""
        if k == "enlace":
            extra = f" → {e['href'][:100]}"
        elif k == "campo" and is_sensitive_field(e):
            extra = " (sensible: lo escribes tú)"
        lines.append(f"[{e['id']}] {k} «{e['text'] or e['name'] or e['type']}»{extra}")
    return {"url": page.url, "title": page.title(), "text": text[:MAX_TEXT] + ("…" if len(text) > MAX_TEXT else ""),
            "elements": "\n".join(lines) or "(sin enlaces, botones ni campos visibles)"}


def _element(w: _BrowserWorker, element_id: Any) -> Dict[str, Any]:
    try:
        el = w.elements[int(element_id)]
    except (KeyError, ValueError, TypeError):
        raise BrowserError(f"No hay ningún elemento [{element_id}] en la página actual. Usa browser_read para verlos.")
    return el


def _locator(w: _BrowserWorker, element_id: Any):
    return w.page.locator(f'[data-edith-id="{int(element_id)}"]').first


def _check_url(url: str) -> str:
    url = (url or "").strip()
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise BrowserError("Solo puedo abrir direcciones web http:// o https://.")
    return url


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except BrowserError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"El navegador falló: {type(e).__name__}: {str(e)[:200]}"}


# ---------------------------------------------------------------- herramientas
def browser_open(url: str) -> Dict[str, Any]:
    def run(w):
        page = w.ensure_page()
        page.goto(_check_url(url), timeout=NAV_TIMEOUT_MS)
        return _snapshot(w)
    return _safe(lambda: _worker.call(run))


def browser_read() -> Dict[str, Any]:
    def run(w):
        if w.page is None:
            raise BrowserError("No hay ninguna página abierta. Usa browser_open primero.")
        return _snapshot(w)
    return _safe(lambda: _worker.call(run))


def browser_follow_link(element_id: Any) -> Dict[str, Any]:
    def run(w):
        el = _element(w, element_id)
        if _kind(el) != "enlace":
            raise BrowserError(f"[{element_id}] no es un enlace sino un {_kind(el)}. Para botones usa browser_click.")
        _check_url(el["href"])
        w.page.goto(el["href"], timeout=NAV_TIMEOUT_MS)
        return _snapshot(w)
    return _safe(lambda: _worker.call(run))


def browser_fill(element_id: Any, text: str) -> Dict[str, Any]:
    def run(w):
        el = _element(w, element_id)
        if _kind(el) not in ("campo",):
            raise BrowserError(f"[{element_id}] no es un campo de texto ({_kind(el)}).")
        if is_sensitive_field(el):
            raise BrowserError("Ese campo es sensible (contraseña, código o datos de pago): no lo escribo yo. "
                               "Pídele al usuario que lo escriba: browser_show abre la ventana.")
        loc = _locator(w, element_id)
        if el["tag"] == "select":
            loc.select_option(label=str(text))
        else:
            loc.fill(str(text))
        return {"status": "escrito", "element": int(element_id), "field": el["text"] or el["name"]}
    return _safe(lambda: _worker.call(run))


def browser_click(element_id: Any) -> Dict[str, Any]:
    def run(w):
        el = _element(w, element_id)
        _locator(w, element_id).click(timeout=10_000)
        try:
            w.page.wait_for_load_state("load", timeout=10_000)
        except Exception:
            pass
        return {"clicked": el["text"] or el["name"], **_snapshot(w)}
    return _safe(lambda: _worker.call(run))


def browser_download(element_id: Any = None, url: str = "") -> Dict[str, Any]:
    def run(w):
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        if url:
            target = _check_url(url)
            w.ensure_page()
            resp = w.ctx.request.get(target, timeout=NAV_TIMEOUT_MS, max_redirects=5)
            if not resp.ok:
                raise BrowserError(f"La descarga respondió HTTP {resp.status}.")
            body = resp.body()
            if len(body) > MAX_DOWNLOAD_BYTES:
                raise BrowserError("El archivo pasa de 50 MB: no lo descargo.")
            name = Path(urlparse(target).path).name or "descarga"
            dest = _unique(DOWNLOADS_DIR / re.sub(r'[<>:"/\\|?*]', "_", name))
            dest.write_bytes(body)
        else:
            _element(w, element_id)
            with w.page.expect_download(timeout=NAV_TIMEOUT_MS) as info:
                _locator(w, element_id).click()
            dl = info.value
            dest = _unique(DOWNLOADS_DIR / re.sub(r'[<>:"/\\|?*]', "_", dl.suggested_filename or "descarga"))
            dl.save_as(str(dest))
            if dest.stat().st_size > MAX_DOWNLOAD_BYTES:
                dest.unlink()
                raise BrowserError("El archivo pasa de 50 MB: lo borré.")
        return {"status": "descargado", "file": f"descargas/{dest.name}", "bytes": dest.stat().st_size,
                "note": "Quedó en el workspace (carpeta descargas)."}
    return _safe(lambda: _worker.call(run, timeout=120))


def browser_show() -> Dict[str, Any]:
    def run(w):
        w.ensure_page(headed=True)
        try:
            w.page.bring_to_front()
        except Exception:
            pass
        return {"status": "visible", "url": w.page.url,
                "note": "La ventana de Edge de EDITH está abierta: el usuario puede iniciar sesión o escribir lo sensible."}
    return _safe(lambda: _worker.call(run))


def browser_close() -> Dict[str, Any]:
    def run(w):
        w._close(keep_pw=True)
        return {"status": "cerrado"}
    return _safe(lambda: _worker.call(run))


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    return path


def browser_active() -> bool:
    """Hay una página abierta: el modelo ve el resto de herramientas del navegador (ahorra contexto)."""
    return _worker.ctx is not None


def describe_element(element_id: Any) -> str:
    el = _worker.elements.get(int(element_id)) if str(element_id).isdigit() else None
    label = f"[{element_id}] «{el['text'] or el['name']}»" if el else f"[{element_id}]"
    return f"{label} en {_worker.last_url}" if _worker.last_url else label


BROWSER_HANDLERS = {
    "browser_open": browser_open, "browser_read": browser_read, "browser_follow_link": browser_follow_link,
    "browser_fill": browser_fill, "browser_click": browser_click, "browser_download": browser_download,
    "browser_show": browser_show, "browser_close": browser_close,
}

_ID = {"element_id": {"type": "integer", "description": "Número del elemento, tal como aparece entre [ ] en la página."}}
BROWSER_TOOLS_METADATA = [
    {"name": "browser_open",
     "description": ("Abre una página en el navegador propio de EDITH (Edge) para INTERACTUAR con ella: iniciar trámites, "
                     "llenar formularios, comparar precios, descargar archivos. Devuelve el texto y una lista numerada de "
                     "enlaces, botones y campos. Para solo leer un artículo usa read_web_page."),
     "parameters": {"type": "object", "properties": {"url": {"type": "string", "description": "Dirección web."}},
                    "required": ["url"]}},
    {"name": "browser_read", "description": "Vuelve a leer la página abierta en el navegador (texto y elementos numerados).",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "browser_follow_link", "description": "Sigue un ENLACE de la página abierta (por su número).",
     "parameters": {"type": "object", "properties": _ID, "required": ["element_id"]}},
    {"name": "browser_fill",
     "description": "Escribe en un CAMPO de la página (búsqueda, nombre, dirección...). Nunca contraseñas ni tarjetas: esas las escribe el usuario.",
     "parameters": {"type": "object", "properties": {**_ID, "text": {"type": "string"}}, "required": ["element_id", "text"]}},
    {"name": "browser_click",
     "description": "Pulsa un BOTÓN o casilla de la página (enviar, buscar, aceptar...). El usuario lo autoriza antes.",
     "parameters": {"type": "object", "properties": _ID, "required": ["element_id"]}},
    {"name": "browser_download",
     "description": "Descarga un archivo (PDF, etc.) pulsando su elemento o desde una URL directa. Se guarda en el workspace/descargas. El usuario lo autoriza antes.",
     "parameters": {"type": "object", "properties": {**_ID, "url": {"type": "string"}}}},
    {"name": "browser_show",
     "description": "Muestra la ventana del navegador de EDITH para que el usuario inicie sesión, escriba datos sensibles o vea la página.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "browser_close", "description": "Cierra el navegador de EDITH.", "parameters": {"type": "object", "properties": {}}},
]
