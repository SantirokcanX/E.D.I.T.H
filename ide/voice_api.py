"""Rutas de «Oye EDITH»: la interfaz manda los tramos de voz del micrófono y aquí se transcriben en local.

El reconocimiento de voz del navegador (Web Speech API) no sirve dentro de la app de escritorio:
WebView2 lo expone pero falla con «network» al segundo de arrancar. Además, en Chrome o Edge manda
el audio a la nube. Con Whisper local funciona igual en la app y en el navegador, y sin internet.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from agent.config import Config
from agent.voice.wake_word import MAX_SECONDS, SAMPLE_RATE, get_wake_listener

router = APIRouter()
MAX_BYTES = SAMPLE_RATE * 2 * MAX_SECONDS  # PCM de 16 bits, mono


@router.get("/api/voice/wake/status")
def wake_status():
    return get_wake_listener().status()


@router.post("/api/voice/wake/prepare")
def wake_prepare():
    """Carga (y la primera vez descarga) el modelo en segundo plano; la interfaz espera a `ready`.
    La interfaz solo lo pide cuando va a escuchar («Oye EDITH» activo o el botón 🎙️)."""
    listener = get_wake_listener()
    listener.prepare()
    return listener.status()


@router.post("/api/voice/wake/listen")
async def wake_listen(request: Request, mode: str = Query("wake", pattern="^(wake|command)$")):
    """Cuerpo: PCM 16 bits little-endian, mono, 16 kHz (un tramo con voz, hasta 15 s).
    mode=command: la orden tras «Oye EDITH» o el botón 🎙️ (este funciona aunque «Oye EDITH» esté apagado)."""
    if mode == "wake" and not Config.WAKE_WORD_ENABLED:
        raise HTTPException(status_code=409, detail="«Oye EDITH» está desactivado en Ajustes")
    length = int(request.headers.get("content-length") or 0)
    if length > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Tramo de voz demasiado largo")
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:  # sin Content-Length (chunked): cortar igual
            raise HTTPException(status_code=413, detail="Tramo de voz demasiado largo")
    listener = get_wake_listener()
    if not listener.ready:
        listener.prepare()
        return {"text": "", "wake": False, "command": "", "busy": True, "loading": True, "ms": 0}
    try:
        return await asyncio.to_thread(listener.listen, bytes(body), mode)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"No pude transcribir el audio: {exc}")
