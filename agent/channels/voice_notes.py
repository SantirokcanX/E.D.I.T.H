"""Notas de voz (Fase 9): audio entrante -> texto (faster-whisper local) y texto -> nota de voz Ogg/Opus.

WhatsApp solo muestra un audio como "nota de voz" (con onda y botón de reproducir) si es
Ogg/Opus mono. edge-tts entrega MP3 (o WAV con el respaldo SAPI5), así que se transcodifica
con PyAV, que ya trae libopus: no hace falta instalar ffmpeg.
"""

import asyncio
import io
import threading
from fractions import Fraction
from pathlib import Path
from typing import Optional

from ..config import Config

_model = None
_model_lock = threading.Lock()


def _whisper():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel  # import perezoso: tarda y pesa
            _model = WhisperModel(Config.WHISPER_MODEL, device=Config.WHISPER_DEVICE,
                                  compute_type=Config.WHISPER_COMPUTE_TYPE)
        return _model


def decode_16k_mono(audio: bytes):
    """Cualquier audio -> muestras float32 mono a 16 kHz (lo que espera Whisper).
    Se decodifica aquí y no dentro de faster-whisper: su decodificador usa un parámetro de
    PyAV (metadata_errors) que ya no existe en PyAV 19+."""
    import av
    import numpy as np

    chunks = []
    resampler = av.AudioResampler(format="flt", layout="mono", rate=16000)
    with av.open(io.BytesIO(audio)) as src:
        for frame in src.decode(audio=0):
            for rf in resampler.resample(frame):
                chunks.append(rf.to_ndarray().reshape(-1))
        for rf in resampler.resample(None):
            chunks.append(rf.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, dtype=np.float32)


def transcribe(audio: bytes, language: str = "es") -> str:
    """Transcribe una nota de voz (ogg/opus, mp3, wav, m4a...). La primera vez descarga el modelo."""
    samples = decode_16k_mono(audio)
    if samples.size < 1600:  # < 0.1 s
        return ""
    model = _whisper()
    segments, _info = model.transcribe(samples, language=language, vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


def to_ogg_opus(audio: bytes) -> bytes:
    """Convierte cualquier audio a Ogg/Opus mono 48 kHz (formato de nota de voz de WhatsApp)."""
    import av

    out_buf = io.BytesIO()
    with av.open(io.BytesIO(audio)) as src, av.open(out_buf, mode="w", format="ogg") as dst:
        stream = dst.add_stream("libopus", rate=48000)
        stream.layout = "mono"
        stream.bit_rate = 32000
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        pts = 0
        for frame in src.decode(audio=0):
            for rf in resampler.resample(frame):
                rf.pts = pts
                rf.time_base = Fraction(1, 48000)
                pts += rf.samples
                for packet in stream.encode(rf):
                    dst.mux(packet)
        for rf in resampler.resample(None):
            rf.pts = pts
            rf.time_base = Fraction(1, 48000)
            pts += rf.samples
            for packet in stream.encode(rf):
                dst.mux(packet)
        for packet in stream.encode(None):
            dst.mux(packet)
    return out_buf.getvalue()


async def synthesize_voice_note(text: str) -> Optional[bytes]:
    """Texto -> nota de voz Ogg/Opus con la voz actual de EDITH (edge-tts, o SAPI5 sin internet)."""
    from ..voice.voice_engine import get_voice_engine

    path = await get_voice_engine().synthesize_async(text)
    if not path:
        return None
    try:
        data = Path(path).read_bytes()
        return await asyncio.to_thread(to_ogg_opus, data)
    finally:
        try:
            Path(path).unlink()
        except OSError:
            pass
