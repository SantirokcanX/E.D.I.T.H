"""Entorno aislado para las pruebas funcionales: datos en una carpeta temporal y un modelo simulado.

Se importa ANTES que ide.server: redirige todo lo que EDITH escribe en disco (recordatorios,
claves, sesiones, Heartbeat, bóveda de Obsidian) para no tocar los datos reales.
"""
import functools
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # acentos y emojis en la consola de Windows

os.environ["OLLAMA_WARMUP"] = "false"
os.environ["HEARTBEAT_ENABLED"] = "false"  # el daemon real no corre: se llama tick() a mano
os.environ["WHATSAPP_ENABLED"] = "false"
os.environ["MORNING_BRIEFING_TIME"] = ""  # sin resumen matutino automático (escribiría en una bóveda)
for var in ("EDITH_API_TOKEN", "EDITH_BRIDGE_SECRET", "EDITH_ALLOWED_HOSTS"):
    os.environ.pop(var, None)
TMP = Path(tempfile.mkdtemp(prefix="edith_pruebas_"))
VAULT = TMP / "vault"
VAULT.mkdir()
os.environ["OBSIDIAN_VAULT_PATH"] = str(VAULT)
# Carpeta de datos de EDITH (agent/paths.py) en la temporal: nunca la real de %LOCALAPPDATA%\EDITH
os.environ["EDITH_HOME"] = str(TMP / "home")

from agent.config import Config  # noqa: E402

Config.reload()
Config.OBSIDIAN_VAULT_PATH = str(VAULT)

import agent.tools.reminder_tools as rt  # noqa: E402
rt.REMINDERS_FILE = TMP / "reminders.json"
import agent.channels.security as sec  # noqa: E402
sec.CHANNELS_DIR = TMP / "channels"
sec.BRIDGE_SECRET_FILE = TMP / "channels" / "bridge_secret"
sec.API_TOKEN_FILE = TMP / "channels" / "api_token"
import agent.memory.memory_manager as mm  # noqa: E402
mm._global_memory_manager = mm.MemoryManager(data_dir=str(TMP / "data"))
import agent.channels.conversations as conv  # noqa: E402
conv.MemoryManager = functools.partial(mm.MemoryManager, data_dir=str(TMP / "data"))
import agent.heartbeat.daemon as dm  # noqa: E402
dm.STATE_FILE = TMP / "heartbeat_state.json"

from agent.providers.base import AgentStepResponse, BaseLLMProvider, ToolCall  # noqa: E402


class FakeProvider(BaseLLMProvider):
    """Modelo simulado. `plan(messages)` permite guionizar llamadas a herramientas en una prueba."""
    delay = 0.0
    seen_tools = []
    plan = None

    def is_available(self):
        return True, "ok"

    def generate_step(self, messages, tools_metadata, on_thought_chunk=None, on_content_chunk=None, think=None):
        FakeProvider.seen_tools = [t["name"] for t in tools_metadata]
        if FakeProvider.plan:
            scripted = FakeProvider.plan(messages)
            if scripted is not None:
                return scripted
        last = next((m for m in reversed(messages) if m["role"] in ("user", "tool")), {})
        if last.get("role") == "user" and "powershell" in str(last.get("content", "")).lower():
            return AgentStepResponse(tool_calls=[ToolCall("run_system_command", {"command": "echo hola"})])
        if last.get("role") == "user" and "resumen matutino" in str(last.get("content", "")).lower():
            return AgentStepResponse(content="Buenos días. Hoy tienes: entregar informe.")
        time.sleep(FakeProvider.delay)
        text = "Claro, aquí estoy. **Todo bien** y $x^2$ listo."
        if last.get("role") == "tool":
            text = "Resultado de herramienta: " + str(last.get("content"))[:120]
        if on_content_chunk:
            for w in text.split(" "):
                on_content_chunk(w + " ")
        return AgentStepResponse(content=text)


results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def summary() -> int:
    passed = sum(ok for _, ok in results)
    print(f"\n{passed}/{len(results)} pruebas OK")
    for name, ok in results:
        if not ok:
            print(f"  FALLÓ: {name}")
    return 0 if passed == len(results) else 1
