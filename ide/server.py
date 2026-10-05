"""EDITH Studio: FastAPI & WebSockets backend server for the Web IDE & Companion Hub."""

import asyncio
import json
import os
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from agent.config import Config
from agent.providers import get_provider
from agent.core.reasoning_agent import ReasoningAgent, AgentCallbacks
from agent.coworking.team import CoworkingTeam, TeamMemberEvent
from agent.voice.voice_engine import get_voice_engine
from agent.memory.memory_manager import get_memory_manager
from agent.learning.error_learner import get_error_learner
from agent.tools.workspace_tools import WORKSPACE_DIR, save_to_workspace, read_workspace_file, list_workspace_files
from agent.tools.system_tools import get_system_status, open_application, run_system_command, control_system_volume
from agent.tools.screen_tools import capture_screen, analyze_screen, SCREENSHOTS_DIR

app = FastAPI(title="EDITH Studio IDE & Companion Hub")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR = BASE_DIR / "data" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

import threading
from agent.providers.ollama_provider import ensure_ollama_running

# Instancia global del agente y equipo
if Config.PROVIDER == "ollama":
    threading.Thread(target=ensure_ollama_running, daemon=True).start()

provider = get_provider()
edith_agent = ReasoningAgent(provider=provider, max_iterations=Config.MAX_ITERATIONS)
coworking_team = CoworkingTeam(provider=provider)
voice_engine = get_voice_engine()
memory_manager = get_memory_manager()
error_learner = get_error_learner()


class WorkspaceFileRequest(BaseModel):
    filename: str
    content: str


class VoiceSelectRequest(BaseModel):
    voice_key: str


class SystemAppRequest(BaseModel):
    app_name: str


class SystemVolumeRequest(BaseModel):
    action: str


@app.get("/api/system/status")
def api_system_status():
    return get_system_status()


@app.post("/api/system/app")
def api_system_app(req: SystemAppRequest):
    res = open_application(req.app_name)
    return {"result": res}


@app.post("/api/system/volume")
def api_system_volume(req: SystemVolumeRequest):
    res = control_system_volume(req.action)
    return {"result": res}


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
def api_select_voice(req: VoiceSelectRequest):
    ok = voice_engine.set_voice(req.voice_key)
    if not ok:
        raise HTTPException(status_code=400, detail="Voz no encontrada")
    return {"status": "ok", "current_voice": voice_engine.current_voice_info}


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
def api_get_sessions():
    return memory_manager.list_sessions()


@app.get("/api/learnings")
def api_get_learnings():
    return error_learner.learnings


@app.get("/api/audio/{filename}")
def api_get_audio(filename: str):
    file_path = AUDIO_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(file_path, media_type="audio/mpeg")


@app.post("/api/screen/capture")
def api_capture_screen():
    res = capture_screen(area="full")
    return res


@app.get("/api/workspace/screenshot/{filename}")
def api_get_screenshot(filename: str):
    file_path = SCREENSHOTS_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Captura no encontrada")
    return FileResponse(file_path, media_type="image/png")


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            action = payload.get("action", "query")
            
            if action == "query":
                user_prompt = payload.get("prompt", "").strip()
                mode = payload.get("mode", "standard")
                speak_response = payload.get("speak", True)

                if not user_prompt:
                    continue

                if mode == "coworking":
                    await websocket.send_json({
                        "type": "status",
                        "text": "Activando protocolo de Co-Working en equipo (EDITH, Scout y Auditor)..."
                    })

                    loop = asyncio.get_event_loop()

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
                        lambda: coworking_team.collaborate(user_prompt, on_event=on_team_event)
                    )

                    audio_url = None
                    if speak_response and voice_engine.enabled:
                        audio_file = await voice_engine.synthesize_async(result["answer"])
                        if audio_file:
                            audio_url = f"/api/audio/{Path(audio_file).name}"

                    await websocket.send_json({
                        "type": "final_answer",
                        "content": result["answer"],
                        "sources": result.get("sources", []),
                        "audio_url": audio_url
                    })

                else:
                    loop = asyncio.get_event_loop()

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

                    callbacks = AgentCallbacks(
                        on_iteration_start=on_iteration_start,
                        on_thought_chunk=on_thought_chunk,
                        on_tool_call=on_tool_call,
                        on_tool_result=on_tool_result
                    )

                    res = await loop.run_in_executor(
                        None,
                        lambda: edith_agent.run(user_prompt, callbacks=callbacks)
                    )

                    audio_url = None
                    if speak_response and voice_engine.enabled and res.answer:
                        audio_file = await voice_engine.synthesize_async(res.answer)
                        if audio_file:
                            audio_url = f"/api/audio/{Path(audio_file).name}"

                    await websocket.send_json({
                        "type": "final_answer",
                        "content": res.answer,
                        "thoughts": res.thoughts,
                        "sources": res.sources,
                        "audio_url": audio_url
                    })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            err_msg = str(e)
            if "10061" in err_msg or "ConnectError" in err_msg:
                err_msg = (
                    "No se pudo conectar con el motor local de Ollama (http://localhost:11434). "
                    "EDITH está intentando iniciarlo automáticamente en segundo plano. "
                    "Por favor espera unos segundos y vuelve a enviar tu mensaje."
                )
            await websocket.send_json({"type": "error", "message": err_msg})
        except Exception:
            pass


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
