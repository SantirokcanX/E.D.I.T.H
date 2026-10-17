"""Pruebas de la Fase 5 (teclado), Fase 6 (aviso al terminar tareas largas) y Fase 2 (diagramas y
notas del día en la bóveda). No escribe en ninguna ventana real: el teclado se prueba con un Windows
simulado y las notificaciones de Windows se interceptan.
Uso:  python tests/test_teclado_avisos.py   (desde la raíz del proyecto, con el .venv activado)
"""
import os
import time
from datetime import datetime

os.environ["ML_ENABLED"] = "false"
from entorno import TMP, VAULT, Config, FakeProvider, check, sec, summary  # noqa: E402

import sys  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import agent.channels.notifier  # noqa: E402,F401
# agent.channels exporta la instancia «notifier» con el mismo nombre que el módulo: el módulo, de sys.modules
notifier_mod = sys.modules["agent.channels.notifier"]
import ide.server as srv  # noqa: E402
import ide.setup_api as setup_api  # noqa: E402
from agent import tools as tools_pkg  # noqa: E402
from agent.core import safety  # noqa: E402
from agent.core.reasoning_agent import AgentCallbacks, ReasoningAgent  # noqa: E402
from agent.providers.base import AgentStepResponse, ToolCall  # noqa: E402
from agent.tools import keyboard_tools as kb  # noqa: E402
from agent.tools.diagram_tools import save_diagram  # noqa: E402
from agent.tools.workspace_tools import save_to_workspace  # noqa: E402

toasts = []
notifier_mod.show_toast = lambda title, body: toasts.append((title, body)) or True


# ======================= 1. Teclado (Fase 5) =======================
check("atajos: «ctrl+shift+s» -> Ctrl, Shift, S", kb.parse_keys("ctrl+shift+s") == [0x11, 0x10, ord("S")])
check("teclas con nombre en español e inglés", kb.parse_keys("intro") == kb.parse_keys("enter") == [0x0D]
      and kb.parse_keys("alt+f4") == [0x12, 0x73])
try:
    kb.parse_keys("ctrl+teletransportar")
    check("una tecla inventada se rechaza", False)
except ValueError:
    check("una tecla inventada se rechaza", True)
check("sin pasos -> error", kb.validate_steps([]) is not None)
check("demasiados pasos -> error", "Demasiados pasos" in kb.validate_steps([{"action": "wait", "value": "1"}] * 61))
check("demasiado texto -> error", "Demasiado texto" in kb.validate_steps([{"action": "type", "value": "x" * 4001}]))
check("espera de más de 10 s o no numérica -> error",
      kb.validate_steps([{"action": "wait", "value": "20000"}]) and kb.validate_steps([{"action": "wait", "value": "1s"}]))
check("acción desconocida -> error", "debe ser" in kb.validate_steps([{"action": "click", "value": "x"}]))
check("pasos válidos -> sin error", kb.validate_steps([{"action": "type", "value": "hola"}, {"action": "keys", "value": "ctrl+s"},
                                                       {"action": "wait", "value": "300"}]) is None)


class FakeUser32:
    """Windows simulado: registra lo que se pulsa y deja cambiar la ventana del frente."""
    def __init__(self):
        self.events, self.foreground = [], 111

    def SendInput(self, n, arr, size):
        for i in range(n):
            ki = arr[i].u.ki
            self.events.append((ki.wVk, ki.wScan, ki.dwFlags))
        return n

    def GetForegroundWindow(self):
        return self.foreground


fake_u = FakeUser32()
kb._user32 = lambda: fake_u
kb.find_window = lambda target: (111, "Sin título: Bloc de notas") if "bloc" in target.lower() else None
kb._focus = lambda hwnd: True
if os.name != "nt":
    kb.sys.platform = "win32"

kb._windows = lambda: [(111, "Sin título: Bloc de notas"), (222, "EDITH")]
r = kb.keyboard_actions("Excel", [{"action": "type", "value": "hola"}])
check("ventana que no existe: error y no escribe nada", "No encontré" in r.get("error", "") and fake_u.events == [], r)
check("...y lista las ventanas abiertas, sin la de EDITH", "Bloc de notas" in r.get("error", "")
      and "; EDITH" not in r.get("error", "") and not r.get("error", "").endswith("EDITH"))
r = kb.keyboard_actions("Bloc de notas", [{"action": "type", "value": "Sí ñ😀"}, {"action": "keys", "value": "ctrl+s"}])
scans = [s for vk, s, f in fake_u.events if f & kb.KEYEVENTF_UNICODE and not f & kb.KEYEVENTF_KEYUP]
expected = [int.from_bytes("Sí ñ😀".encode("utf-16-le")[i:i + 2], "little") for i in range(0, len("Sí ñ😀".encode("utf-16-le")), 2)]
check("escribe con acentos, ñ y emojis (Unicode, como teclearlos)", r.get("status") == "hecho" and scans == expected, (r, scans))
combo = [(vk, f & kb.KEYEVENTF_KEYUP) for vk, s, f in fake_u.events if vk]
check("Ctrl+S: baja Ctrl, baja S, sube S, sube Ctrl", combo[-4:] == [(0x11, 0), (ord("S"), 0), (ord("S"), 2), (0x11, 2)], combo[-4:])
fake_u.events.clear()
r = kb.keyboard_actions("Bloc de notas", [{"action": "type", "value": "línea 1\nlínea 2"}])
check("un salto de línea se teclea como Intro", any(vk == 0x0D for vk, s, f in fake_u.events))


def switch_after_first(*a, **k):
    fake_u.foreground = 999  # el usuario cambió de ventana


fake_u.events.clear()
fake_u.foreground = 111
real_type = kb.type_text
kb.type_text = lambda text: (real_type(text), switch_after_first())
r = kb.keyboard_actions("Bloc de notas", [{"action": "type", "value": "uno"}, {"action": "type", "value": "dos"}])
kb.type_text = real_type
check("si cambias de ventana, se detiene antes del siguiente paso", r.get("status") == "detenido" and r.get("steps_done") == 1, r)
fake_u.foreground = 111

check("teclado: siempre pide permiso y solo desde la laptop",
      "keyboard_actions" in safety.CONFIRM_ALWAYS and "keyboard_actions" in tools_pkg.LOCAL_ONLY_TOOLS)
title, detail = safety.describe_action("keyboard_actions", {"target_window": "Bloc de notas",
                                                            "steps": [{"action": "type", "value": "hola"},
                                                                      {"action": "keys", "value": "ctrl+s"}]})
check("la confirmación muestra la ventana y todos los pasos", "Bloc de notas" in title and "escribir «hola»" in detail
      and "pulsar ctrl+s" in detail, (title, detail))


class KeyboardPlan(FakeProvider):
    def generate_step(self, messages, tools_metadata, on_thought_chunk=None, on_content_chunk=None, think=None):
        last = messages[-1]
        if last["role"] == "user":
            return AgentStepResponse(tool_calls=[ToolCall("keyboard_actions", {
                "target_window": "Bloc de notas", "steps": [{"action": "type", "value": "hola"}]})])
        return AgentStepResponse(content="Resultado: " + str(last.get("content"))[:80])


asked = []
fake_u.events.clear()
agent = ReasoningAgent(provider=KeyboardPlan(), max_iterations=3)
res = agent.run("escribe hola en el bloc de notas", AgentCallbacks(on_confirm=lambda t, a, r: asked.append(t) or False))
check("el agente pide permiso antes de teclear; si no autorizas, no teclea",
      asked == ["keyboard_actions"] and fake_u.events == [], (asked, len(fake_u.events)))
asked.clear()
res = agent.run("escribe hola en el bloc de notas", AgentCallbacks(on_confirm=lambda t, a, r: asked.append(t) or True))
check("autorizado: teclea", asked == ["keyboard_actions"] and len(fake_u.events) > 0 and "hecho" in res.answer, res.answer[:80])
blocked = ReasoningAgent(provider=KeyboardPlan(), max_iterations=3, blocked_tools=set(tools_pkg.LOCAL_ONLY_TOOLS))
check("desde WhatsApp/teléfono el modelo ni siquiera ve la herramienta",
      "keyboard_actions" not in [t["name"] for t in blocked.tools_metadata])

flag = {"on": False}
tools_pkg.OPTIONAL_TOOL_GROUPS.append((lambda: flag["on"], [{"name": "herramienta_opcional", "description": "x",
                                                              "parameters": {"type": "object", "properties": {}}}]))
before = "herramienta_opcional" in [t["name"] for t in agent.tools_metadata]
flag["on"] = True
after = "herramienta_opcional" in [t["name"] for t in agent.tools_metadata]
tools_pkg.OPTIONAL_TOOL_GROUPS.pop()
check("las herramientas opcionales solo aparecen cuando están configuradas (y en vivo)", not before and after)

# ======================= 2. Aviso al terminar tareas largas (Fase 6) =======================
Config.NOTIFY_CHANNELS = ["ui", "toast"]
ws_key = object()
srv.ui_active[ws_key] = False
Config.LONG_TASK_NOTIFY_SECONDS = 25
srv.notify_if_away(ws_key, "Listo: tu informe está en el workspace.", elapsed=30)
check("respuesta larga sin mirar EDITH -> notificación de Windows", toasts and "Terminé tu tarea" in toasts[-1][0]
      and "informe" in toasts[-1][1], toasts[-1:])
n = len(toasts)
srv.notify_if_away(ws_key, "rápida", elapsed=3)
check("respuesta rápida -> sin notificación", len(toasts) == n)
srv.ui_active[ws_key] = True
srv.notify_if_away(ws_key, "larga pero la estabas mirando", elapsed=60)
check("si la estabas mirando -> sin notificación", len(toasts) == n)
srv.ui_active[ws_key] = False
Config.NOTIFY_CHANNELS = ["ui"]
srv.notify_if_away(ws_key, "larga", elapsed=60)
check("si apagaste las notificaciones de Windows en Ajustes, se respeta", len(toasts) == n)
srv.ui_active.pop(ws_key)

fake = FakeProvider()
srv.provider = fake
srv.edith_agent.provider = fake
srv.ml_engine = None
srv.voice_engine.enabled = False
Config.NOTIFY_CHANNELS = ["ui", "toast"]
Config.LONG_TASK_NOTIFY_SECONDS = 0.2
FakeProvider.delay = 0.4
token = sec.get_api_token()
local = TestClient(srv.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50002))
n = len(toasts)
with local.websocket_connect("ws://127.0.0.1:8000/ws/chat",
                             headers={"Authorization": f"Bearer {token}", "Origin": "http://127.0.0.1:8000"}) as ws:
    ws.send_json({"action": "presence", "active": False})
    ws.send_json({"action": "query", "prompt": "hazme un informe largo", "mode": "standard", "reasoning": "fast", "speak": False})
    while ws.receive_json().get("type") != "final_answer":
        pass
    time.sleep(0.3)
check("de punta a punta: la pestaña dice «no te estoy mirando» y al terminar llega el aviso",
      len(toasts) == n + 1 and "Terminé tu tarea" in toasts[-1][0], toasts[-1:])
n = len(toasts)
with local.websocket_connect("ws://127.0.0.1:8000/ws/chat",
                             headers={"Authorization": f"Bearer {token}", "Origin": "http://127.0.0.1:8000"}) as ws:
    ws.send_json({"action": "presence", "active": True})
    ws.send_json({"action": "query", "prompt": "otro informe", "mode": "standard", "reasoning": "fast", "speak": False})
    while ws.receive_json().get("type") != "final_answer":
        pass
    time.sleep(0.3)
check("...y mirándola, no", len(toasts) == n)
FakeProvider.delay = 0.0

n = len(toasts)
setup_api._downloads_finished({"items": [{"model": "qwen3:4b", "status": "listo"}], "ok": True})
check("modelos descargados sin mirar EDITH -> aviso", len(toasts) == n + 1 and "qwen3:4b" in toasts[-1][1], toasts[-1:])
setup_api._downloads_finished({"items": [{"model": "x", "status": "error"}], "ok": False})
check("si la descarga falla, también avisa", "falló" in toasts[-1][0])
Config.NOTIFY_CHANNELS = ["ui"]

# ======================= 3. Diagramas y notas del día en la bóveda (Fase 2) =======================
Config.OBSIDIAN_VAULT_PATH = str(VAULT)
Config.OBSIDIAN_SAVE_WORKSPACE = True
msg = save_diagram("Flujo de pedidos", "mermaid", "graph TD\n  A-->B")
note = VAULT / "03 - Conocimiento" / "Diagramas" / "Flujo de pedidos.md"
check("un diagrama Mermaid también queda como nota en la bóveda", note.exists() and "```mermaid\ngraph TD" in note.read_text(encoding="utf-8")
      and "Obsidian" in msg, msg)
check("con etiquetas de EDITH", "  - diagrama" in note.read_text(encoding="utf-8"))
save_diagram("logo_simple", "svg", "<svg xmlns='http://www.w3.org/2000/svg'></svg>")
svg_note = VAULT / "03 - Conocimiento" / "Diagramas" / "logo simple.md"
check("un SVG se guarda junto a la nota y se incrusta", (VAULT / "03 - Conocimiento" / "Diagramas" / "logo simple.svg").exists()
      and "![[logo simple.svg]]" in svg_note.read_text(encoding="utf-8"))
save_to_workspace("notas_del_dia.md", "# Hoy\n- revisar el instalador")
daily = VAULT / "01 - Diario" / f"{datetime.now().strftime('%Y-%m-%d')} - Notas del día.md"
check("las notas del día van al Diario de hoy", daily.exists() and "revisar el instalador" in daily.read_text(encoding="utf-8"))
save_to_workspace("notas_del_dia.md", "# Hoy\n- instalador listo")
text = daily.read_text(encoding="utf-8")
check("al volver a guardarlas se actualiza la misma nota (sin duplicar)", "instalador listo" in text and "revisar" not in text)
save_to_workspace("otro.md", "nada")
check("otros archivos del workspace no se copian", not list(VAULT.rglob("otro.md")))
Config.OBSIDIAN_SAVE_WORKSPACE = False
save_diagram("No copiar", "mermaid", "graph TD\n  X-->Y")
check("con la opción apagada, no se copia", not (VAULT / "03 - Conocimiento" / "Diagramas" / "No copiar.md").exists())
Config.OBSIDIAN_SAVE_WORKSPACE = True
Config.OBSIDIAN_VAULT_PATH = str(TMP / "no_tengo_obsidian")
msg = save_diagram("Sin bóveda", "mermaid", "graph TD\n  X-->Y")
check("sin bóveda no se crea ninguna carpeta y el diagrama se guarda igual",
      not (TMP / "no_tengo_obsidian").exists() and "workspace" in msg and "Obsidian" not in msg)
Config.OBSIDIAN_VAULT_PATH = str(VAULT)

raise SystemExit(summary())
