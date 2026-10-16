"""EDITH Desktop (Fase 15.1): aplicación nativa de Windows.

  * Sin consola: se abre con EDITH.exe (o pythonw) y registra todo en %LOCALAPPDATA%\\EDITH\\logs.
  * Icono en la bandeja junto al reloj: abrir, nueva conversación, pausar avisos, salir.
  * Cerrar la ventana la OCULTA: EDITH sigue con el Heartbeat, WhatsApp y los recordatorios.
    "Salir" (bandeja) la apaga de verdad. Apagar o cerrar sesión en Windows no se bloquea.
  * Una sola instancia: abrirla otra vez solo muestra la ventana existente.
  * Puerto libre automático (8000 si está libre) o fijo con EDITH_PORT en .env.
  * Atajo global Win + Shift + E para mostrar/ocultar EDITH desde cualquier programa.
"""

import ctypes
import logging
import os
import socket
import sys
import threading
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agent.paths import APP_DIR, EDITH_HOME, LOGS_DIR  # noqa: E402  (también migra los datos la 1.ª vez)

APP_ID = "EDITH.Desktop"
MUTEX_NAME = "Local\\EDITH_Desktop_Instance"
SHOW_EVENT_NAME = "Local\\EDITH_Desktop_Show"
QUIT_EVENT_NAME = "Local\\EDITH_Desktop_Quit"  # el desinstalador (Fase 15.4) lo usa para cerrar EDITH
# Icono cuadrado multi-tamaño (16-256 px) generado a partir del logo: Windows no muestra bien
# iconos no cuadrados de un solo tamaño (edith.ico mide 101x106).
ICON_ICO = APP_DIR / "desktop" / "assets" / "edith-app.ico"
ICON_PNG = APP_DIR / "desktop" / "assets" / "edith-tray.png"
WEBVIEW_DIR = EDITH_HOME / "webview"  # perfil de WebView2: recuerda permisos (micrófono) y preferencias

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.restype = wintypes.HANDLE
user32.LoadImageW.restype = wintypes.HANDLE
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
ERROR_ALREADY_EXISTS = 183
log = logging.getLogger("edith.desktop")


# ---------------------------------------------------------------- registro
def setup_logging():
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOGS_DIR / "edith-desktop.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Sin consola (pythonw / EDITH.exe) stdout y stderr no existen: todo va al registro
    if sys.stdout is None or sys.stderr is None or not sys.stdout.isatty():
        stream = open(LOGS_DIR / "edith-desktop.out.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = stream


# ---------------------------------------------------------------- instancia única
def acquire_single_instance() -> bool:
    """True si somos la primera instancia. Si no, pide a la existente que se muestre."""
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return True
    EVENT_MODIFY_STATE = 0x0002
    handle = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
    if handle:
        user32.AllowSetForegroundWindow(-1)  # deja que la otra instancia pase al frente
        kernel32.SetEvent(handle)
        kernel32.CloseHandle(handle)
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


LOADING_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#0a0a0f;color:#ece9f5;font-family:'Segoe UI',sans-serif}
.c{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px}
.d{width:34px;height:34px;border:3px solid #2a2a38;border-top-color:#9b5cf6;border-radius:50%;animation:s 0.9s linear infinite}
@keyframes s{to{transform:rotate(360deg)}} p{margin:0;color:#a6a2bd;font-size:14px}</style></head>
<body><div class="c"><div class="d"></div><h2 style="margin:0">EDITH</h2><p>Iniciando…</p></div></body></html>"""


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

    # ------------------------------------------------ servidor
    def start_server(self):
        import uvicorn
        self.port = pick_port()
        os.environ["EDITH_PORT"] = str(self.port)  # lo usan el bridge de WhatsApp y el Heartbeat
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
            self.window.load_url(f"http://127.0.0.1:{self.port}/")
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
            pystray.MenuItem(pause_label, toggle_pause),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Abrir carpeta de datos", lambda: os.startfile(str(EDITH_HOME))),
            pystray.MenuItem("Salir", lambda: self.quit()),
        )
        image = Image.open(ICON_PNG if ICON_PNG.exists() else ICON_ICO)
        self.tray = pystray.Icon("EDITH", image, "EDITH", menu)
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
        try:
            self.window.destroy()
        except Exception:
            os._exit(0)

    def shutdown(self):
        self.quitting = True
        if self.hotkey_thread_id:
            user32.PostThreadMessageW(self.hotkey_thread_id, 0x0012, 0, 0)  # WM_QUIT
        if self.tray:
            self.tray.stop()
        if self.server:
            self.server.should_exit = True  # dispara el apagado ordenado (detiene el bridge de WhatsApp)
            self.server_thread.join(timeout=10)
        log.info("EDITH cerrada")

    # ------------------------------------------------ principal
    def run(self):
        import webview
        from agent.providers.ollama_provider import ensure_ollama_running

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        threading.Thread(target=ensure_ollama_running, daemon=True).start()
        self.start_server()

        self.window = webview.create_window(
            "EDITH", html=LOADING_HTML, width=1320, height=880, min_size=(960, 640), background_color="#0a0a0f")
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


def main():
    setup_logging()
    if not acquire_single_instance():
        log.info("EDITH ya estaba abierta: se muestra la ventana existente")
        return
    try:
        DesktopApp().run()
    except Exception:
        log.exception("Error fatal en EDITH Desktop")
        user32.MessageBoxW(None, f"EDITH no pudo iniciar. Revisa los registros en:\n{LOGS_DIR}", "EDITH", 0x10)
        raise


if __name__ == "__main__":
    main()
