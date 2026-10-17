"""EDITH Studio: FastAPI & WebSockets backend server for the Web IDE & Companion Hub."""

import asyncio
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from agent.config import Config
from agent.paths import APP_DIR, DATA_DIR, FROZEN, VERSION
from agent.providers import get_provider
from agent.core.reasoning_agent import ReasoningAgent, AgentCallbacks
from agent.core.safety import describe_action
from agent.coworking.team import CoworkingTeam, TeamMemberEvent
from agent.voice.voice_engine import get_voice_engine
from agent.memory.memory_manager import get_memory_manager
from agent.learning.error_learner import get_error_learner
from agent.tools.workspace_tools import WORKSPACE_DIR, save_to_workspace, read_workspace_file, list_workspace_files
from agent.tools.system_tools import (get_system_status, open_application, run_system_command,
                                      control_system_volume, APP_ALIASES)
from agent.tools.obsidian_tools import get_vault_path, sync_edith_session, search_vault
from agent.channels.notifier import notifier
from agent.channels.security import get_api_token
from agent import ratelimit
from ide.auth import AccessGuard, access_link_hint
from ide.channels_api import router as channels_router, start_channels, stop_channels
from ide.setup_api import router as setup_router, same_origin
from ide.code_api import router as code_router
from ide.voice_api import router as voice_router
from agent.setup import settings as setup_settings

try:  # ML opcional
    from agent.ml import get_ml_engine, ROUTES as ML_ROUTES
except Exception:  # pragma: no cover
    get_ml_engine = None
    ML_ROUTES = []

app = FastAPI(title="EDITH Studio IDE & Companion Hub", version=VERSION)


def content_security_policy(host: str) -> str:
    """Fase 14: solo código de la propia EDITH (librerías en vendor/, sin CDN ni scripts en línea).
    Los estilos en línea siguen permitidos: KaTeX y Mermaid los usan para dibujar fórmulas y diagramas."""
    ws = f" ws://{host} wss://{host}" if host and all(c.isalnum() or c in ".-:[]" for c in host) else ""
    return ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' blob: data:; "
            f"connect-src 'self'{ws}; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")


@app.middleware("http")
async def revalidate_static(request, call_next):
    """La interfaz se revalida siempre (ETag): tras actualizar EDITH no se queda un app.js viejo en caché."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    # Nadie puede incrustar EDITH en un iframe (p. ej. para engañar al usuario con el botón "Autorizar")
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = content_security_policy(request.headers.get("host", ""))
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# Fase 14: token, Host y Origin. Se añade el último para que sea la capa más externa.
app.add_middleware(AccessGuard)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = APP_DIR / "ide" / "static"  # en la app empaquetada (Fase 15.3): _internal\ide\static
STATIC_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Instancia global del agente y equipo
provider = get_provider()
edith_agent = ReasoningAgent(provider=provider, max_iterations=Config.MAX_ITERATIONS)
coworking_team = CoworkingTeam(provider=provider)
voice_engine = get_voice_engine()
memory_manager = get_memory_manager()
error_learner = get_error_learner()
ml_engine = None
if get_ml_engine and Config.ML_ENABLED:
    try:
        ml_engine = get_ml_engine()
    except Exception as exc:
        print(f"[ML] desactivado: {exc}")

# Precargar el modelo en segundo plano: el primer mensaje ya no espera a que Ollama lo cargue
if Config.OLLAMA_WARMUP and hasattr(provider, "warmup"):
    threading.Thread(target=provider.warmup, daemon=True).start()


class WorkspaceFileRequest(BaseModel):
    filename: str
    content: str


class VoiceSelectRequest(BaseModel):
    voice_key: str


class MLAnalyzeRequest(BaseModel):
    text: str


class MLFeedbackRequest(BaseModel):
    text: str
    route: str


class SystemAppRequest(BaseModel):
    app_name: str


class SystemVolumeRequest(BaseModel):
    action: str


class SessionRenameRequest(BaseModel):
    title: str


@app.get("/api/system/status")
def api_system_status():
    return get_system_status()


@app.post("/api/system/app")
def api_system_app(req: SystemAppRequest):
    # Los botones del panel solo lanzan las apps conocidas: la ruta no sirve para ejecutar cualquier cosa
    if req.app_name.lower().strip() not in APP_ALIASES:
        raise HTTPException(status_code=400, detail="Aplicación no disponible desde el panel")
    res = open_application(req.app_name)
    return {"result": res}


@app.post("/api/system/volume")
def api_system_volume(req: SystemVolumeRequest):
    res = control_system_volume(req.action)
    return {"result": res}


@app.get("/api/ml/status")
def api_ml_status():
    if not ml_engine:
        return {"enabled": False}
    return {"enabled": True, "auto_route": Config.ML_AUTO_ROUTE,
            "threshold": Config.ML_AUTO_THRESHOLD, **ml_engine.status()}


@app.post("/api/ml/analyze")
def api_ml_analyze(req: MLAnalyzeRequest):
    if not ml_engine:
        raise HTTPException(status_code=503, detail="ML desactivado")
    a = ml_engine.analyze(req.text)
    return {"route": a.route, "confidence": a.confidence, "probs": a.probs,
            "memories": [{"text": m["text"], "score": m["score"]} for m in a.memories]}


@app.post("/api/ml/feedback")
def api_ml_feedback(req: MLFeedbackRequest):
    if not ml_engine:
        raise HTTPException(status_code=503, detail="ML desactivado")
    if req.route not in ML_ROUTES:
        raise HTTPException(status_code=400, detail=f"Ruta inválida. Opciones: {ML_ROUTES}")
    ml_engine.feedback(req.text, req.route)
    return {"status": "ok"}


@app.post("/api/ml/train")
def api_ml_train():
    if not ml_engine:
        raise HTTPException(status_code=503, detail="ML desactivado")
    return {"indexed": ml_engine.train_from_sessions(), **ml_engine.status()}


@app.get("/api/version")
def api_version():
    return {"version": VERSION, "packaged": FROZEN}


@app.get("/api/status")
def get_status():
    avail, msg = provider.is_available()
    return {
        "agent": "EDITH",
        "provider": Config.PROVIDER,
        "model": getattr(provider, "model", "N/A"),
        "available": avail,
        "status_message": msg,
        "session_id": memory_manager.current_session_id,
        "voice_key": voice_engine.voice_key,
        "voice_name": voice_engine.current_voice_info["name"],
        "voice_enabled": voice_engine.enabled,
        "available_voices": [
            {"key": k, "name": v["name"]} for k, v in voice_engine.VOICES.items()
        ]
    }


@app.post("/api/voice/select")
def api_select_voice(req: VoiceSelectRequest, request: Request):
    ok = voice_engine.set_voice(req.voice_key)
    if not ok:
        raise HTTPException(status_code=400, detail="Voz no encontrada")
    # Antes solo cambiaba en memoria: al reiniciar volvía la voz del .env. Se guarda como en Ajustes,
    # y solo desde esta computadora (igual que el resto de ajustes)
    saved = False
    try:
        same_origin(request)
        saved = setup_settings.save({"EDITH_VOICE": voice_engine.voice_key}).get("ok", False)
    except HTTPException:
        pass
    return {"status": "ok", "current_voice": voice_engine.current_voice_info, "saved": saved}


@app.get("/api/workspace")
def api_list_workspace():
    return list_workspace_files()


@app.get("/api/workspace/file")
def api_get_workspace_file(path: str = Query(...)):
    content = read_workspace_file(path)
    return {"path": path, "content": content}


@app.post("/api/workspace/file")
def api_save_workspace_file(req: WorkspaceFileRequest):
    result = save_to_workspace(req.filename, req.content)
    return {"message": result, "path": req.filename}


@app.get("/api/sessions")
def api_get_sessions(q: str = Query("")):
    sessions = memory_manager.search_sessions(q) if q.strip() else memory_manager.list_sessions()
    current = memory_manager.current_session_id
    return [{**s, "active": s["id"] == current} for s in sessions]


@app.get("/api/sessions/{session_id}")
def api_get_session(session_id: str):
    data = memory_manager.get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    # Solo lo que se muestra en el chat: mensajes del usuario, respuestas y herramientas usadas
    messages = []
    for m in data.get("messages", []):
        role = m.get("role")
        if role == "user" and m.get("content"):
            messages.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            for tc in m.get("tool_calls") or []:
                messages.append({"role": "tool", "tool": tc.get("name", ""), "args": tc.get("arguments", {})})
            if m.get("content"):
                messages.append({"role": "assistant", "content": m["content"]})
    return {"id": data["id"], "title": data.get("title", ""), "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at", ""), "messages": messages}


@app.post("/api/sessions/new")
def api_new_session():
    edith_agent.reset_history()
    return {"id": memory_manager.current_session_id}


@app.post("/api/sessions/{session_id}/load")
def api_load_session(session_id: str):
    if not edith_agent.load_specific_session(session_id):
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {"id": session_id}


@app.patch("/api/sessions/{session_id}")
def api_rename_session(session_id: str, req: SessionRenameRequest):
    if not memory_manager.rename_session(session_id, req.title):
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    return {"status": "ok"}


@app.delete("/api/sessions/{session_id}")
def api_delete_session(session_id: str):
    was_active = session_id == memory_manager.current_session_id
    if not memory_manager.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    if was_active:
        edith_agent.reset_history()
    return {"status": "ok", "active_id": memory_manager.current_session_id}


@app.post("/api/sessions/{session_id}/obsidian")
def api_session_to_obsidian(session_id: str):
    res = sync_edith_session(session_id)
    if "error" in res:
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@app.get("/api/obsidian/status")
def api_obsidian_status():
    vault = get_vault_path()
    return {"vault": str(vault), "exists": vault.exists(), "auto_sync": Config.OBSIDIAN_AUTO_SYNC}


@app.get("/api/obsidian/search")
def api_obsidian_search(q: str = Query(...)):
    return search_vault(q)


@app.get("/api/learnings")
def api_get_learnings():
    return error_learner.learnings


@app.get("/api/audio/{filename}")
def api_get_audio(filename: str):
    file_path = (AUDIO_DIR / filename).resolve()
    if file_path.parent != AUDIO_DIR.resolve() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    media_type = "audio/wav" if file_path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(file_path, media_type=media_type)


async def send_voice(websocket: WebSocket, text: str):
    """Sintetiza la voz DESPUÉS de mostrar la respuesta: el texto ya no espera al audio."""
    try:
        audio_file = await voice_engine.synthesize_async(text)
        if audio_file:
            await websocket.send_json({"type": "audio_ready", "audio_url": f"/api/audio/{Path(audio_file).name}"})
    except Exception:
        pass


CONFIRM_TIMEOUT_SECONDS = 120  # sin respuesta del usuario, la acción se rechaza sola


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """Lee los mensajes de la pestaña sin bloquearse: las consultas van a una cola que se atiende
    en orden y las respuestas a "¿Autorizas?" llegan mientras el agente espera."""
    await websocket.accept()
    ui_clients.add(websocket)
    queries: asyncio.Queue = asyncio.Queue()
    pending: Dict[str, asyncio.Future] = {}  # confirmaciones de ESTA pestaña esperando respuesta
    worker = asyncio.create_task(_chat_worker(websocket, queries, pending))

    try:
        while True:
            payload = json.loads(await websocket.receive_text())
            action = payload.get("action", "query")
            if action == "confirm":
                fut = pending.get(str(payload.get("id", "")))
                if fut and not fut.done():
                    fut.set_result(payload.get("approved") is True)
            elif action == "presence":  # la pestaña dice si la estás mirando (para avisar al terminar)
                ui_active[websocket] = payload.get("active") is True
            elif action == "query":
                if not ratelimit.chat.hit("ui:" + ratelimit.client_ip(websocket.scope)):
                    await websocket.send_json({"type": "error", "message": (
                        f"Vas muy rápido: máximo {Config.CHAT_LIMIT_PER_MINUTE} consultas por minuto. "
                        "Espera unos segundos y vuelve a intentarlo.")})
                    continue
                await queries.put(payload)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        ui_clients.discard(websocket)
        ui_active.pop(websocket, None)
        for fut in pending.values():  # pestaña cerrada = acción rechazada
            if not fut.done():
                fut.set_result(False)
        worker.cancel()


async def _chat_worker(websocket: WebSocket, queries: asyncio.Queue, pending: Dict[str, asyncio.Future]):
    while True:
        payload = await queries.get()
        try:
            started = time.monotonic()
            answer = await _handle_query(websocket, payload, pending)
            notify_if_away(websocket, answer, time.monotonic() - started)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass


async def _ask_confirmation(websocket: WebSocket, pending: Dict[str, asyncio.Future],
                            tool: str, args: Dict[str, Any], reason: str) -> bool:
    """Muestra el modal "EDITH quiere ejecutar: … ¿Autorizas?" y espera la respuesta."""
    req_id = secrets.token_urlsafe(9)
    fut = asyncio.get_running_loop().create_future()
    pending[req_id] = fut
    try:
        title, detail = describe_action(tool, args)
        await websocket.send_json({"type": "confirm_request", "id": req_id, "tool": tool, "args": args,
                                   "title": title, "detail": detail,
                                   "reason": reason, "timeout": CONFIRM_TIMEOUT_SECONDS})
        return await asyncio.wait_for(fut, CONFIRM_TIMEOUT_SECONDS)
    except Exception:  # sin respuesta a tiempo o pestaña cerrada
        try:
            await websocket.send_json({"type": "confirm_expired", "id": req_id})
        except Exception:
            pass
        return False
    finally:
        pending.pop(req_id, None)


async def _handle_query(websocket: WebSocket, payload: Dict[str, Any], pending: Dict[str, asyncio.Future]):
    user_prompt = payload.get("prompt", "").strip()
    mode = payload.get("mode", "standard")
    # Razonamiento: "fast" = directo, "deep" = pensar a fondo, "auto" = EDITH decide
    reasoning = payload.get("reasoning", "auto")
    think_choice = {"fast": False, "deep": True}.get(reasoning)
    if think_choice is not None and Config.ML_ENABLED and payload.get("prompt", "").strip():
        # Elegiste 🔬 o ⚡ a mano: EDITH aprende cuándo prefieres que piense a fondo
        try:
            from agent.ml.deep_router import get_deep_router
            await asyncio.to_thread(get_deep_router().learn, payload["prompt"].strip(), think_choice)
        except Exception as e:
            print(f"[ML] no se pudo aprender la preferencia de razonamiento: {e}")
    speak_response = payload.get("speak", True)

    if not user_prompt:
        return

    ml_analysis = None
    if ml_engine:
        try:
            ml_analysis = ml_engine.analyze(user_prompt)
            if mode == "auto":  # el ML decide entre chat directo y equipo
                mode = ("coworking"
                        if ml_analysis.route == "coworking"
                        and ml_analysis.confidence >= Config.ML_AUTO_THRESHOLD
                        else "standard")
                await websocket.send_json({
                    "type": "ml_route",
                    "route": ml_analysis.route,
                    "confidence": round(ml_analysis.confidence, 3),
                    "mode": mode
                })
        except Exception:
            ml_analysis = None
    if mode == "auto":
        mode = "standard"
    if ml_engine:
        ml_engine.log_query(user_prompt, ml_analysis.route if ml_analysis else None,
                            mode == "coworking")

    loop = asyncio.get_running_loop()

    if mode == "coworking":
        await websocket.send_json({
            "type": "status",
            "text": "Activando protocolo de Co-Working en equipo (EDITH, Scout y Auditor)..."
        })

        def on_team_event(event: TeamMemberEvent):
            asyncio.run_coroutine_threadsafe(
                websocket.send_json({
                    "type": "team_event",
                    "member": event.member,
                    "role": event.role,
                    "content": event.content,
                    "action_type": event.action_type
                }),
                loop
            )

        result = await loop.run_in_executor(
            None,
            lambda: coworking_team.collaborate(
                user_prompt,
                on_event=on_team_event,
                context=ml_analysis.context if ml_analysis else ""
            )
        )
        if ml_engine:
            ml_engine.remember_turn(user_prompt)

        await websocket.send_json({
            "type": "final_answer",
            "content": result["answer"],
            "sources": result.get("sources", []),
            "session_id": memory_manager.current_session_id
        })
        if speak_response and voice_engine.enabled and result.get("answer"):
            await send_voice(websocket, result["answer"])
        return result.get("answer") or ""

    def on_iteration_start(it: int):
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "iteration_start", "iteration": it}),
            loop
        )

    def on_thought_chunk(chunk: str):
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "thought_chunk", "chunk": chunk}),
            loop
        )

    def on_content_chunk(chunk: str):
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "content_chunk", "chunk": chunk}),
            loop
        )

    def on_tool_call(tool: str, args: dict):
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "tool_call", "tool": tool, "args": args}),
            loop
        )

    def on_tool_result(tool: str, output: any):
        count = len(output) if isinstance(output, list) else 1
        asyncio.run_coroutine_threadsafe(
            websocket.send_json({"type": "tool_result", "tool": tool, "count": count}),
            loop
        )

    def on_confirm(tool: str, args: dict, reason: str) -> bool:
        # Se llama desde el hilo del agente, que se queda esperando la respuesta del usuario
        fut = asyncio.run_coroutine_threadsafe(_ask_confirmation(websocket, pending, tool, args, reason), loop)
        try:
            return fut.result(timeout=CONFIRM_TIMEOUT_SECONDS + 10)
        except Exception:
            return False

    callbacks = AgentCallbacks(
        on_iteration_start=on_iteration_start,
        on_thought_chunk=on_thought_chunk,
        on_content_chunk=on_content_chunk,
        on_tool_call=on_tool_call,
        on_tool_result=on_tool_result,
        on_confirm=on_confirm
    )

    deep = edith_agent.resolve_think(user_prompt, think_choice)
    await websocket.send_json({"type": "reasoning", "deep": deep})

    res = await loop.run_in_executor(
        None,
        lambda: edith_agent.run(user_prompt, callbacks=callbacks, think=deep)
    )

    await websocket.send_json({
        "type": "final_answer",
        "content": res.answer,
        "thoughts": res.thoughts,
        "sources": res.sources,
        "deep": res.deep_thinking,
        "session_id": memory_manager.current_session_id
    })
    if speak_response and voice_engine.enabled and res.answer:
        await send_voice(websocket, res.answer)
    return res.answer or ""


# ---------- Fases 9-11: canales remotos, notificaciones y Heartbeat ----------
ui_clients: set = set()
ui_active: Dict[Any, bool] = {}  # pestaña -> ¿la estás mirando? (Fase 6)


def any_ui_active() -> bool:
    return any(ui_active.get(ws, True) for ws in list(ui_clients))


def notify_if_away(websocket, answer: Optional[str], elapsed: float):
    """Fase 6: si una respuesta tardó y no estabas mirando EDITH, aviso de Windows al terminar."""
    if not answer or elapsed < Config.LONG_TASK_NOTIFY_SECONDS or ui_active.get(websocket, True):
        return
    text = " ".join(answer.split())
    notifier.toast_if_enabled("Terminé tu tarea", (text[:160] + "…") if len(text) > 160 else text)


async def broadcast_ui(event: dict):
    """Envía un evento (p. ej. una notificación del Heartbeat) a todas las pestañas abiertas."""
    for ws in list(ui_clients):
        try:
            await ws.send_json(event)
        except Exception:
            ui_clients.discard(ws)


@app.on_event("startup")
async def _startup_channels():
    # Puerto en uso (lo fija main.py o la app de escritorio); EDITH_PORT es solo el ajuste del usuario
    port = int(os.getenv("EDITH_RUNTIME_PORT") or "8000")
    get_api_token()  # se genera aquí la primera vez, no en la primera petición
    print(f"[Seguridad] Interfaz y API protegidas con token. Para entrar desde otro dispositivo: {access_link_hint()}")
    start_channels(provider, broadcast_ui, asyncio.get_running_loop(), port=port)


@app.on_event("shutdown")
async def _shutdown_channels():
    stop_channels()


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def index_page():
    """index.html con la versión del archivo VERSION en los enlaces a CSS y JS: tras actualizar
    EDITH, WebView2 no reutiliza un app.js viejo (Fase 15.3)."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("{{EDITH_VERSION}}", VERSION))


app.include_router(channels_router)
app.include_router(code_router)  # Fase 7: ▶ Ejecutar (Python, con confirmación)
app.include_router(setup_router)  # Fase 15.2: asistente de primer arranque y Ajustes
app.include_router(voice_router)  # «Oye EDITH» con Whisper local
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
