"""Botón ▶ Ejecutar de los bloques de código Python (Fase 7).

Solo lo dispara una persona: el botón está en la interfaz, pide confirmación mostrando el código y
la ruta exige el token, el mismo Origin y esta computadora (no se ejecuta nada desde otro
dispositivo ni lo puede pedir el modelo). El código corre con tus permisos, en
workspace/ejecuciones y con un tiempo máximo; no es un entorno aislado.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.paths import FROZEN, WORKSPACE_DIR
from ide.setup_api import same_origin

router = APIRouter()
RUN_DIR = WORKSPACE_DIR / "ejecuciones"
TIMEOUT_SECONDS = 30
MAX_CODE = 50_000
MAX_OUTPUT = 20_000
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class RunRequest(BaseModel):
    code: str
    language: str = "python"


def _interpreter(script: Path, out: Path, err: Path):
    """(comando, ¿la salida va a archivos?). En EDITH.exe no hay python.exe: se usa el intérprete
    empaquetado (EDITH.exe --run-python), que además trae numpy, etc."""
    if FROZEN:
        return [sys.executable, "--run-python", str(script), str(out), str(err)], True
    console = Path(sys.executable).with_name("python.exe")  # pythonw.exe no tiene salida estándar
    return [str(console if console.exists() else sys.executable), "-X", "utf8", str(script)], False


def _kill_tree(proc: subprocess.Popen):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, creationflags=_NO_WINDOW)
    else:
        proc.kill()


def run_python(code: str) -> dict:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    script = RUN_DIR / f"ejecucion_{stamp}_{os.getpid()}.py"
    script.write_text(code, encoding="utf-8")
    out, err = script.with_suffix(".out.txt"), script.with_suffix(".err.txt")
    cmd, to_files = _interpreter(script, out, err)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    for secret in ("EDITH_API_TOKEN", "EDITH_BRIDGE_SECRET", "TWILIO_AUTH_TOKEN", "HA_TOKEN", "EMAIL_PASSWORD",
                   "GEMINI_API_KEY", "CALENDAR_ICS_URLS"):
        env.pop(secret, None)  # el código no ve los secretos de EDITH
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=str(RUN_DIR), env=env, creationflags=_NO_WINDOW,
                            stdout=subprocess.DEVNULL if to_files else subprocess.PIPE,
                            stderr=subprocess.DEVNULL if to_files else subprocess.PIPE)
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        stdout, stderr = proc.communicate()
    if to_files:
        stdout = out.read_bytes() if out.exists() else b""
        stderr = err.read_bytes() if err.exists() else b""
    for f in (out, err):
        try:
            f.unlink()
        except OSError:
            pass

    def clip(b):
        text = (b or b"").decode("utf-8", errors="replace")
        return text[:MAX_OUTPUT] + ("\n… (salida recortada)" if len(text) > MAX_OUTPUT else "")

    return {"stdout": clip(stdout), "stderr": clip(stderr), "exit_code": proc.returncode, "timed_out": timed_out,
            "seconds": round(time.monotonic() - started, 2), "script": f"ejecuciones/{script.name}"}


@router.post("/api/code/run", dependencies=[Depends(same_origin)])
def code_run(req: RunRequest):
    if req.language.lower() not in ("python", "py", "python3"):
        raise HTTPException(status_code=400, detail="Por ahora solo se ejecuta Python.")
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="No hay código.")
    if len(req.code) > MAX_CODE:
        raise HTTPException(status_code=400, detail="El código es demasiado largo para ejecutarlo aquí.")
    return run_python(req.code)
