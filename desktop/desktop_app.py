"""EDITH Desktop (Fase 15.1): aplicación nativa de Windows.

  * Sin consola: se abre con EDITH.exe (o pythonw) y registra todo en %LOCALAPPDATA%\\EDITH\\logs.
  * Icono en la bandeja junto al reloj: abrir, nueva conversación, pausar avisos, salir.
  * Cerrar la ventana la OCULTA: EDITH sigue con el Heartbeat, WhatsApp y los recordatorios.
    "Salir" (bandeja) la apaga de verdad. Apagar o cerrar sesión en Windows no se bloquea.
  * Una sola instancia: abrirla otra vez solo muestra la ventana existente.
  * Puerto libre automático (8000 si está libre) o fijo con EDITH_PORT en .env.
  * Atajo global Win + Shift + E para mostrar/ocultar EDITH desde cualquier programa.
  * Fase 15.3: también es el punto de entrada de EDITH.exe empaquetado con PyInstaller
    (build/edith.spec). EDITH.exe --self-test comprueba el paquete sin abrir ventanas.
    EDITH.exe --access-link muestra el enlace con token para otro dispositivo (no hay main.py).
"""

import ctypes
import hashlib
import json
import logging
import multiprocessing
import os
import re
import socket
import sys
import threading
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.paths import APP_DIR, EDITH_HOME, FROZEN, LOGS_DIR, VERSION  # noqa: E402  (también migra los datos la 1.ª vez)


def _instance_suffix() -> str:
    """Una instancia por carpeta de datos. Con un EDITH_HOME propio (pruebas, copia portátil) los nombres
    llevan una huella de esa carpeta: no muestran ni cierran la EDITH normal, ni el desinstalador a ellas."""
    if not os.environ.get("EDITH_HOME"):
        return ""
    return "_" + hashlib.sha1(str(EDITH_HOME).lower().encode("utf-8")).hexdigest()[:8]


APP_ID = "EDITH.Desktop"
_SUFFIX = _instance_suffix()
MUTEX_NAME = "Local\\EDITH_Desktop_Instance" + _SUFFIX
SHOW_EVENT_NAME = "Local\\EDITH_Desktop_Show" + _SUFFIX
QUIT_EVENT_NAME = "Local\\EDITH_Desktop_Quit" + _SUFFIX  # el desinstalador (Fase 15.4) lo usa para cerrar EDITH
# Icono cuadrado multi-tamaño (16-256 px) generado a partir del logo: Windows no muestra bien
# iconos no cuadrados de un solo tamaño (edith.ico mide 101x106).
ICON_ICO = APP_DIR / "desktop" / "assets" / "edith-app.ico"
ICON_PNG = APP_DIR / "desktop" / "assets" / "edith-tray.png"
WEBVIEW_DIR = EDITH_HOME / "webview"  # perfil de WebView2: recuerda permisos (micrófono) y preferencias

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.AttachConsole.argtypes = [wintypes.DWORD]
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.OpenMutexW.restype = wintypes.HANDLE
user32.LoadImageW.restype = wintypes.HANDLE
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
ERROR_ALREADY_EXISTS = 183
log = logging.getLogger("edith.desktop")


# ---------------------------------------------------------------- registro
class _SkipConnectionReset(logging.Filter):
    """En Windows, cuando la ventana (WebView2) corta una conexión de golpe, asyncio registra
    ConnectionResetError (WinError 10054) como ERROR con traza aunque no falló nada."""

    def filter(self, record):
        return not (record.exc_info and isinstance(record.exc_info[1], ConnectionResetError))


_closing = threading.Event()  # EDITH se está cerrando (Salir, Windows se apaga u otra EDITH la reemplaza)


class _SkipAbortedWebView(logging.Filter):
    """Si EDITH se cierra mientras su ventana aún arranca, WebView2 aborta (E_ABORT) y pywebview lo anota
    como ERROR. Es consecuencia del cierre, no un fallo: se omite solo en ese caso."""

    def filter(self, record):
        return not (_closing.is_set() and "WebView2 initialization failed" in record.getMessage())


def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOGS_DIR / "edith-desktop.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    logging.getLogger("asyncio").addFilter(_SkipConnectionReset())
    logging.getLogger("pywebview").addFilter(_SkipAbortedWebView())
    # Sin consola (pythonw / EDITH.exe) stdout y stderr no existen: todo va al registro
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        stream = open(LOGS_DIR / "edith-desktop.out.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream


# ---------------------------------------------------------------- instancia única
INSTANCE_FILE = EDITH_HOME / "instance.json"  # qué EDITH está abierta (pid y versión)
_mutex_handle = None


def acquire_single_instance() -> bool:
    """True si somos la primera instancia (y nos quedamos el mutex)."""
    global _mutex_handle
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        _mutex_handle = handle
        return True
    if handle:
        kernel32.CloseHandle(handle)  # no mantener vivo el mutex de la otra instancia
    return False


def show_existing_instance():
    EVENT_MODIFY_STATE = 0x0002
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
    if handle:
        user32.AllowSetForegroundWindow(-1)  # deja que la otra instancia pase al frente
        kernel32.SetEvent(handle)
        kernel32.CloseHandle(handle)


def _version_tuple(text: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", text or "")[:4]) or (0,)


def running_instance_version() -> str:
    """Versión de la EDITH abierta; "" si no lo dice (las anteriores a la 0.1.1 no escribían instance.json)."""
    try:
        return str(json.loads(INSTANCE_FILE.read_text(encoding="utf-8")).get("version", ""))
    except (OSError, ValueError):
        return ""


def write_instance_file():
    try:
        INSTANCE_FILE.write_text(json.dumps({"pid": os.getpid(), "version": VERSION, "packaged": FROZEN}),
                                 encoding="utf-8")
    except OSError:
        pass


def remove_instance_file():
    try:
        if json.loads(INSTANCE_FILE.read_text(encoding="utf-8")).get("pid") == os.getpid():
            INSTANCE_FILE.unlink()
    except (OSError, ValueError):
        pass


def replace_older_instance(timeout: float = 30.0) -> bool:
    """Abriste una EDITH más nueva que la que ya estaba abierta (p. ej. tras actualizar): se cierra la
    vieja con su evento de salida y esta ocupa su lugar. True si la vieja se cerró y ya tenemos el mutex."""
    EVENT_MODIFY_STATE, SYNCHRONIZE = 0x0002, 0x00100000
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, QUIT_EVENT_NAME)
    if not handle:
        return False
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mutex = kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
        if not mutex:  # nadie lo tiene: la vieja ya salió
            return acquire_single_instance()
        kernel32.CloseHandle(mutex)
        time.sleep(0.3)
    return False


# ---------------------------------------------------------------- puerto
def pick_port() -> int:
    """EDITH_PORT fijo si está en .env (necesario para el servidor de la Fase 8);
    si no, 8000 cuando esté libre y, si no, cualquier puerto libre."""
    from agent.config import Config  # noqa: F401  (carga el .env)
    wanted = os.getenv("EDITH_PORT", "auto").strip().lower()
    # Puertos estables antes que uno aleatorio: WebView2 recuerda permisos por origen (incluye el puerto)
    candidates = [int(wanted)] if wanted.isdigit() else [*range(8000, 8011), 0]
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError(f"El puerto {wanted} está ocupado. Cambia EDITH_PORT en .env o cierra el programa que lo usa.")


# ---------------------------------------------------------------- enlace de acceso
def show_access_links(out=None) -> int:
    """EDITH.exe --access-link: el enlace con token para otro dispositivo sin abrir la app (lo mismo que
    Ajustes › Avanzado). Desde una terminal lo escribe en ella; con doble clic, en un cuadro de Windows."""
    from agent.config import Config  # noqa: F401  (carga el .env)
    from ide.auth import access_links_text
    wanted = os.getenv("EDITH_PORT", "auto").strip()
    text = access_links_text(int(wanted) if wanted.isdigit() else 8000)  # auto: 8000 salvo que esté ocupado
    out = sys.stdout if out is None else out
    ATTACH_PARENT_PROCESS = 0xFFFFFFFF
    if out is None and kernel32.AttachConsole(ATTACH_PARENT_PROCESS):  # EDITH.exe no tiene consola propia
        out = open("CONOUT$", "w", encoding="utf-8")
    if out is None:
        user32.MessageBoxW(None, text, "EDITH · enlace de acceso", 0x40)  # MB_ICONINFORMATION
    else:
        print(text, file=out, flush=True)
    return 0


LOADING_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#0a0a0f;color:#ece9f5;font-family:'Segoe UI',sans-serif}
.c{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.d{width:34px;height:34px;border:3px solid #2a2a38;border-top-color:#9b5cf6;border-radius:50%;animation:s 0.9s linear infinite}
@keyframes s{to{transform:rotate(360deg)}} p{margin:0;color:#a6a2bd;font-size:14px}</style></head>
<body><div class="c"><div class="d"></div><h2 style="margin:0">EDITH</h2><p>Iniciando…</p></div></body></html>"""


class DesktopApi:
    """Funciones nativas que la interfaz puede llamar con window.pywebview.api.* (Fase 15.2)."""

    def __init__(self, app: "DesktopApp"):
        self._app = app

    def pick_folder(self, initial: str = ""):
        import webview
        start = initial if initial and Path(initial).is_dir() else str(Path.home() / "Documents")
        result = self._app.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        return result[0] if result else None

    def show_window(self):
        """«Oye EDITH» con la app oculta en la bandeja: mostrar la ventana para ver la respuesta."""
        self._app.show()
        return True

    def open_url(self, url: str):
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            import webbrowser
            webbrowser.open(url)
            return True
        return False


class DesktopApp:
    def __init__(self):
        self.window = None
        self.tray = None
        self.server = None
        self.server_thread = None
        self.port = None
        self.quitting = False
        self.hidden_notice_shown = False
        self.hotkey_thread_id = None
        # --tray: arranque con Windows, directo a la bandeja sin mostrar la ventana
        self.start_hidden = "--tray" in sys.argv

    # ------------------------------------------------ servidor
    def start_server(self):
        import uvicorn
        self.port = pick_port()
        os.environ["EDITH_RUNTIME_PORT"] = str(self.port)  # lo usan el bridge de WhatsApp y el Heartbeat
        os.environ["EDITH_DESKTOP"] = "1"  # Ajustes muestra opciones solo de escritorio (iniciar con Windows)
        config = uvicorn.Config("ide.server:app", host="127.0.0.1", port=self.port,
                                log_level="warning", log_config=None)
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self.server.run, name="edith-server", daemon=True)
        self.server_thread.start()
        log.info("Servidor en http://127.0.0.1:%s · datos en %s", self.port, EDITH_HOME)

    def wait_and_load(self):
        """Muestra 'Iniciando…' hasta que el servidor está listo y luego carga la interfaz."""
        deadline = time.time() + 120
        while not (self.server and self.server.started) and time.time() < deadline:
            if self.server_thread and not self.server_thread.is_alive():
                break
            time.sleep(0.2)
        if self.server and self.server.started:
            # Fase 14: la ventana entra con el enlace de acceso, así no depende de EDITH_LOCAL_AUTOLOGIN.
            # El servidor cambia el token por una cookie HttpOnly y redirige a "/" sin él en la URL.
            from urllib.parse import quote
            from agent.channels.security import get_api_token
            self.window.load_url(f"http://127.0.0.1:{self.port}/?token={quote(get_api_token(), safe='')}")
        else:
            log.error("El servidor no arrancó; revisa %s", LOGS_DIR)
            self.window.load_html(LOADING_HTML.replace("Iniciando…", f"No pude iniciar. Revisa los registros en {LOGS_DIR}"))

    # ------------------------------------------------ ventana
    def on_shown(self):
        """Pone el icono de EDITH en la ventana y en la barra de tareas."""
        try:
            hwnd = int(str(self.window.native.Handle.ToInt64()))
            IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x0080
            sm_small, sm_big = user32.GetSystemMetrics(49), user32.GetSystemMetrics(11)  # SM_CXSMICON, SM_CXICON
            applied = 0
            for size, kind in ((sm_small, 0), (sm_big, 1)):
                hicon = user32.LoadImageW(None, str(ICON_ICO), IMAGE_ICON, size, size, LR_LOADFROMFILE)
                if hicon:
                    user32.SendMessageW(hwnd, WM_SETICON, kind, hicon)
                    applied += 1
            log.info("Icono de la ventana aplicado (%s/2)", applied)
        except Exception as e:
            log.warning("No se pudo poner el icono de la ventana: %s", e)

    def on_closing(self):
        if self.quitting:
            return True
        threading.Thread(target=self.hide, daemon=True).start()
        return False  # cancela el cierre: solo se oculta

    def hide(self):
        self.window.hide()
        if not self.hidden_notice_shown:
            self.hidden_notice_shown = True
            try:
                from agent.channels.notifier import show_toast
                show_toast("EDITH sigue activa", "La encuentras junto al reloj. Para cerrarla del todo: clic derecho > Salir.")
            except Exception:
                pass

    def show(self):
        try:
            self.window.show()
            self.window.restore()
            hwnd = int(str(self.window.native.Handle.ToInt64()))
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
        except Exception as e:
            log.warning("No se pudo mostrar la ventana: %s", e)

    def toggle(self):
        try:
            hwnd = int(str(self.window.native.Handle.ToInt64()))
            visible = user32.IsWindowVisible(hwnd) and user32.GetForegroundWindow() == hwnd
        except Exception:
            visible = False
        self.hide() if visible else self.show()

    def open_settings(self):
        self.show()
        try:
            self.window.evaluate_js("typeof EdithSetup !== 'undefined' && EdithSetup.openSettings()")
        except Exception:
            pass

    def new_chat(self):
        self.show()
        try:
            self.window.evaluate_js("typeof startNewSession === 'function' && startNewSession()")
        except Exception:
            pass

    # ------------------------------------------------ bandeja del sistema
    def start_tray(self):
        import pystray
        from PIL import Image
        from agent.channels.notifier import notifier

        def pause_label(_item):
            return "Reanudar avisos" if notifier.paused else "Pausar avisos 1 h"

        def toggle_pause(icon, _item):
            notifier.resume() if notifier.paused else notifier.pause(60)
            icon.update_menu()

        menu = pystray.Menu(
            pystray.MenuItem("Abrir EDITH", lambda: self.show(), default=True),
            pystray.MenuItem("Nueva conversación", lambda: self.new_chat()),
            pystray.MenuItem("Ajustes", lambda: self.open_settings()),
            pystray.MenuItem(pause_label, toggle_pause),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir carpeta de datos", lambda: os.startfile(str(EDITH_HOME))),
            pystray.MenuItem("Salir", lambda: self.quit()),
        )
        image = Image.open(ICON_PNG if ICON_PNG.exists() else ICON_ICO)
        self.tray = pystray.Icon("EDITH", image, f"EDITH {VERSION}", menu)
        self.tray.run_detached()
        log.info("Icono de la bandeja listo")

    # ------------------------------------------------ cerrar desde fuera (desinstalador, actualizador)
    def watch_quit_event(self):
        handle = kernel32.CreateEventW(None, True, False, QUIT_EVENT_NAME)
        if kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) == 0:
            log.info("Cierre solicitado desde fuera")
            self.quit()

    # ------------------------------------------------ mostrar desde otra instancia
    def watch_show_event(self):
        handle = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
        INFINITE = 0xFFFFFFFF
        while not self.quitting:
            if kernel32.WaitForSingleObject(handle, INFINITE) == 0 and not self.quitting:
                self.show()

    # ------------------------------------------------ atajo global Win + Shift + E
    def watch_hotkey(self):
        spec = os.getenv("EDITH_HOTKEY", "win+shift+e").lower().replace(" ", "")
        if spec in ("", "off", "none", "no"):
            return
        mods = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
        parts = spec.split("+")
        flags = 0x4000  # MOD_NOREPEAT
        for p in parts[:-1]:
            flags |= mods.get(p, 0)
        key = parts[-1].upper()
        if len(key) != 1:
            log.warning("EDITH_HOTKEY no válido: %s", spec)
            return
        self.hotkey_thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, 1, flags, ord(key)):
            log.warning("El atajo %s ya lo usa otro programa", spec)
            return
        log.info("Atajo global %s activo", spec)
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                self.toggle()
        user32.UnregisterHotKey(None, 1)

    # ------------------------------------------------ apagado
    def watch_session_end(self):
        """Si Windows se apaga o cierra sesión, salir de verdad en lugar de ocultarse."""
        try:
            import clr  # noqa: F401  (pythonnet, el mismo que usa pywebview)
            from Microsoft.Win32 import SystemEvents

            def on_ending(_sender, _args):
                self.quitting = True
            SystemEvents.SessionEnding += on_ending
        except Exception as e:
            log.info("Sin aviso de fin de sesión: %s", e)

    def quit(self):
        self.quitting = True
        _closing.set()
        try:
            self.window.destroy()
        except Exception:
            os._exit(0)

    def shutdown(self):
        self.quitting = True
        _closing.set()
        if self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)  # WM_QUIT
        if self.tray:
            self.tray.stop()
        if self.server:
            self.server.should_exit = True  # dispara el apagado ordenado (detiene el bridge de WhatsApp)
            self.server_thread.join(timeout=10)
        remove_instance_file()
        log.info("EDITH cerrada")

    # ------------------------------------------------ principal
    def run(self):
        import webview
        from agent.providers.ollama_provider import ensure_ollama_running

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        threading.Thread(target=ensure_ollama_running, daemon=True).start()
        self.start_server()

        self.window = webview.create_window(
            "EDITH", html=LOADING_HTML, width=1320, height=880, min_size=(960, 640), background_color="#0a0a0f",
            hidden=self.start_hidden, js_api=DesktopApi(self))
        if self.start_hidden:
            self.hidden_notice_shown = True  # al iniciar con Windows no hace falta avisar
        self.window.events.closing += self.on_closing
        self.window.events.shown += self.on_shown

        for target in (self.wait_and_load, self.watch_show_event, self.watch_quit_event, self.watch_hotkey):
            threading.Thread(target=target, daemon=True).start()
        self.watch_session_end()
        self.start_tray()
        try:
            from agent.channels.notifier import register_app_identity
            register_app_identity()
        except Exception:
            pass

        # private_mode=False + storage_path: WebView2 recuerda el permiso del micrófono y localStorage
        webview.start(debug=False, private_mode=False, storage_path=str(WEBVIEW_DIR))  # bloquea hasta "Salir"
        self.shutdown()


def run_python_script(args) -> int:
    """EDITH.exe --run-python script.py salida.txt errores.txt (Fase 7: ▶ Ejecutar en la app empaquetada).
    Usa el intérprete que trae EDITH.exe; la salida va a archivos porque EDITH.exe no tiene consola."""
    import runpy
    import traceback
    script, out, err = (args + ["", "", ""])[:3]
    with open(out or os.devnull, "w", encoding="utf-8") as o, open(err or os.devnull, "w", encoding="utf-8") as e:
        sys.stdout, sys.stderr = o, e
        sys.argv = [script]
        try:
            runpy.run_path(script, run_name="__main__")
            return 0
        except SystemExit as ex:
            return ex.code if isinstance(ex.code, int) else 0
        except BaseException:
            traceback.print_exc()
            return 1


def main():
    multiprocessing.freeze_support()  # EDITH.exe: los procesos hijos de multiprocessing no relanzan la app
    if "--run-python" in sys.argv[1:]:
        i = sys.argv.index("--run-python")
        sys.exit(run_python_script(sys.argv[i + 1:]))
    if "--access-link" in sys.argv[1:]:
        sys.exit(show_access_links())  # antes del registro: la salida va a la terminal, no al log
    setup_logging()
    test_arg = next((a for a in sys.argv[1:] if a.startswith("--self-test")), None)
    if test_arg:
        import self_test  # noqa: PLC0415  (desktop/self_test.py)
        report = test_arg.partition("=")[2] or str(LOGS_DIR / "self-test.txt")
        sys.exit(self_test.run(Path(report)))
    log.info("EDITH %s (%s)", VERSION, "app empaquetada" if FROZEN else "desde el código")
    if not acquire_single_instance():
        running = running_instance_version()
        if _version_tuple(running) < _version_tuple(VERSION):
            # Tras actualizar: abrir la nueva no debe traer al frente la versión vieja que seguía abierta
            log.info("Hay una EDITH %s abierta y esta es la %s: se cierra la anterior", running or "anterior", VERSION)
            if not replace_older_instance():
                log.warning("La EDITH anterior no se cerró: se muestra su ventana")
                show_existing_instance()
                return
        else:
            log.info("EDITH ya estaba abierta: se muestra la ventana existente")
            show_existing_instance()
            return
    write_instance_file()
    try:
        DesktopApp().run()
    except Exception:
        log.exception("Error fatal en EDITH Desktop")
        user32.MessageBoxW(None, f"EDITH no pudo iniciar. Revisa los registros en:\n{LOGS_DIR}", "EDITH", 0x10)
        if FROZEN:
            sys.exit(1)  # en EDITH.exe, sin un segundo cuadro de «excepción no controlada» de PyInstaller
        raise


if __name__ == "__main__":
    main()
