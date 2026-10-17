"""Rutas del asistente de primer arranque y del panel de Ajustes (Fase 15.2)."""

import asyncio
import os
import threading
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from agent.config import Config
from agent.setup import settings as setup_settings
from agent.setup.hardware import diagnose
from agent.setup.models import PullManager
from ide import auth

router = APIRouter()
_pulls = PullManager(Config.OLLAMA_BASE_URL)


def _downloads_finished(progress):
    """Fase 6: si la descarga terminó mientras no mirabas EDITH, aviso de Windows."""
    from agent.channels.notifier import notifier
    from ide import server as srv
    if srv.any_ui_active():
        return
    names = ", ".join(i["model"] for i in progress["items"])
    if progress["ok"]:
        notifier.toast_if_enabled("Modelos descargados", f"Ya puedes usar {names}.")
    elif any(i["status"] == "error" for i in progress["items"]):
        notifier.toast_if_enabled("La descarga de modelos falló", "Abre Ajustes › Modelos para reintentar.")


_pulls.on_finish = _downloads_finished


def same_origin(request: Request):
    """Las rutas que cambian ajustes solo aceptan peticiones de la propia EDITH en esta máquina."""
    host = request.headers.get("host", "")
    if host.split(":")[0] not in ("127.0.0.1", "localhost"):
        raise HTTPException(status_code=403, detail="Solo desde esta computadora")
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != host:
        raise HTTPException(status_code=403, detail="Origen no permitido")


def this_computer(request: Request):
    """Además de same_origin: navegador de esta misma máquina (127.0.0.1) y sin túnel ni proxy delante."""
    same_origin(request)
    if not auth.is_local_browser(request.scope, request.headers):
        raise HTTPException(status_code=403, detail="Solo desde esta computadora")


class SettingsRequest(BaseModel):
    values: Dict[str, Any]


class ModelsRequest(BaseModel):
    models: List[str]


class VoiceSampleRequest(BaseModel):
    voice_key: str


class VaultRequest(BaseModel):
    path: str
    create: bool = False


# ---------------------------------------------------------------- estado del asistente
@router.get("/api/setup/status")
def setup_status():
    state = setup_settings.setup_state()
    return {"completed": bool(state.get("completed_at")), "completed_at": state.get("completed_at"),
            "desktop": setup_settings.is_desktop()}


@router.post("/api/setup/complete", dependencies=[Depends(same_origin)])
def setup_complete():
    setup_settings.mark_setup_complete()
    return {"ok": True}


@router.get("/api/setup/hardware")
def setup_hardware(fast: str = "", deep: str = ""):
    wanted = [m for m in (fast, deep) if m] or None
    return diagnose(Config.OLLAMA_BASE_URL, wanted)


# ---------------------------------------------------------------- ajustes
@router.get("/api/settings")
def settings_get():
    schema = [{**s, "fields": [f for f in s["fields"] if not (f.get("desktop_only") and not setup_settings.is_desktop())]}
              for s in setup_settings.SCHEMA]
    return {"schema": schema, "values": setup_settings.current_values(),
            "env_file": str(Path(__import__("agent.config", fromlist=["env_path"]).env_path))}


@router.post("/api/settings", dependencies=[Depends(same_origin)])
async def settings_save(req: SettingsRequest):
    result = await asyncio.to_thread(setup_settings.save, req.values)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("errors"))
    applied = await asyncio.to_thread(apply_live, result["changed"])
    return {**result, "applied": applied}


def apply_live(changed: List[str]) -> List[str]:
    """Aplica los ajustes nuevos sin reiniciar EDITH."""
    from ide import server as srv
    from ide import channels_api
    done = []
    ollama_keys = {"OLLAMA_MODEL", "OLLAMA_DEEP_MODEL", "OLLAMA_THINK", "OLLAMA_NUM_CTX", "OLLAMA_KEEP_ALIVE", "OLLAMA_BASE_URL"}
    p = srv.provider
    if ollama_keys & set(changed) and hasattr(p, "deep_model"):
        p.model = Config.OLLAMA_MODEL
        p.deep_model = Config.OLLAMA_DEEP_MODEL if Config.OLLAMA_DEEP_MODEL and Config.OLLAMA_DEEP_MODEL != p.model else None
        p.think = Config.OLLAMA_THINK
        p.num_ctx = Config.OLLAMA_NUM_CTX
        p.keep_alive = Config.OLLAMA_KEEP_ALIVE
        p.base_url = Config.OLLAMA_BASE_URL
        p._no_tools.clear()
        p._no_think.clear()
        _pulls.base_url = Config.OLLAMA_BASE_URL
        threading.Thread(target=p.warmup, daemon=True).start()  # cargar el modelo nuevo ya
        done.append("modelos")
    if "EDITH_VOICE" in changed:
        srv.voice_engine.set_voice(Config.EDITH_VOICE)
        done.append("voz")
    if "WHISPER_MODEL" in changed:
        from agent.channels import voice_notes
        voice_notes._model = None  # se cargará el nuevo en la próxima nota de voz
        done.append("transcripción")
    if {"WAKE_WORD_ENABLED", "WAKE_WORD_SENSITIVITY", "WAKE_WORD_MODEL", "WHISPER_MODEL"} & set(changed):
        from agent.voice.wake_word import get_wake_listener
        if {"WAKE_WORD_MODEL", "WHISPER_MODEL"} & set(changed):
            get_wake_listener().reset()  # la interfaz pide el modelo nuevo al recargar el estado
        done.append("oye edith")
    if {"WHATSAPP_ENABLED", "AUTHORIZED_PHONE_NUMBERS"} & set(changed):
        channels_api.restart_bridge()
        done.append("whatsapp")
    if "HEARTBEAT_ENABLED" in changed:
        channels_api.toggle_heartbeat(Config.HEARTBEAT_ENABLED)
        done.append("heartbeat")
    return done


# ---------------------------------------------------------------- modelos
@router.post("/api/setup/models/pull", dependencies=[Depends(same_origin)])
def models_pull(req: ModelsRequest):
    if not req.models:
        raise HTTPException(status_code=400, detail="No hay modelos que descargar")
    if not _pulls.start(req.models):
        raise HTTPException(status_code=409, detail="Ya hay una descarga en curso")
    return _pulls.progress()


@router.get("/api/setup/models/progress")
def models_progress():
    return _pulls.progress()


@router.post("/api/setup/models/cancel", dependencies=[Depends(same_origin)])
def models_cancel():
    _pulls.cancel()
    return {"ok": True}


# ---------------------------------------------------------------- voz
@router.post("/api/setup/voice/sample", dependencies=[Depends(same_origin)])
async def voice_sample(req: VoiceSampleRequest):
    from agent.voice.voice_engine import VoiceEngine
    if req.voice_key not in VoiceEngine.VOICES:
        raise HTTPException(status_code=400, detail="Voz desconocida")
    engine = VoiceEngine(voice_key=req.voice_key)
    path = await engine.synthesize_async("Hola, soy EDITH. Así sonaría mi voz cuando hablemos.")
    if not path:
        raise HTTPException(status_code=503, detail=engine.last_error or "No pude generar la muestra de voz")
    # .wav = respaldo SAPI5 de Windows: la voz neural falló y la muestra NO es la voz elegida
    return {"audio_url": f"/api/audio/{Path(path).name}", "offline": path.endswith(".wav"),
            "voice_id": engine.voice, "reason": engine.last_error}


# ---------------------------------------------------------------- bóveda de Obsidian
@router.post("/api/setup/vault/check", dependencies=[Depends(same_origin)])
def vault_check(req: VaultRequest):
    from agent.tools.obsidian_tools import VAULT_FOLDERS
    p = Path(os.path.expandvars(os.path.expanduser(req.path.strip())))
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Indica la ruta completa de la carpeta")
    if req.create:
        p.mkdir(parents=True, exist_ok=True)
        for folder in VAULT_FOLDERS:
            (p / folder).mkdir(exist_ok=True)
    exists = p.is_dir()
    notes = sum(1 for _ in p.rglob("*.md")) if exists else 0
    writable = False
    if exists:
        probe = p / ".edith_prueba_escritura"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except OSError:
            pass
    return {"path": str(p), "exists": exists, "is_obsidian": (p / ".obsidian").is_dir(), "notes": notes,
            "writable": writable, "has_structure": exists and all((p / f).is_dir() for f in VAULT_FOLDERS)}


# ---------------------------------------------------------------- acceso desde otro dispositivo
@router.post("/api/setup/access-link", dependencies=[Depends(this_computer)])
def access_link(request: Request, response: Response):
    """Enlace con token para abrir EDITH desde otro dispositivo (botón de Ajustes → Avanzado). En la app
    empaquetada no hay main.py: este es el camino. POST: con cookie, el middleware exige además el Origin."""
    response.headers["Cache-Control"] = "no-store"
    port = request.scope["server"][1] if request.scope.get("server") else int(os.getenv("EDITH_RUNTIME_PORT") or 8000)
    return {"remote": auth.remote_access_links(port), "local": auth.local_access_link(port),
            "no_remote": auth.NO_REMOTE_ACCESS}
