"""Natural Voice Engine for EDITH with Conversational Prosody and Multi-voice support."""

import asyncio
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Optional, Dict, List
import edge_tts

PYGAME_INITIALIZED = False
try:
    import pygame
    pygame.mixer.init()
    PYGAME_INITIALIZED = True
except Exception:
    PYGAME_INITIALIZED = False


class VoiceEngine:
    """Motor de síntesis vocal hiper-natural y conversacional para EDITH."""

    VOICES: Dict[str, Dict[str, str]] = {
        "elvira": {
            "id": "es-ES-ElviraNeural",
            "name": "Elvira (Cálida, humana y conversacional)",
            "rate": "-2%",
            "pitch": "+0Hz"
        },
        "dalia": {
            "id": "es-MX-DaliaNeural",
            "name": "Dalia (Serena, suave y clara)",
            "rate": "-3%",
            "pitch": "+0Hz"
        },
        "ximena": {
            "id": "es-ES-XimenaNeural",
            "name": "Ximena (Espontánea, cercana y expresiva)",
            "rate": "-1%",
            "pitch": "+1Hz"
        },
        "salome": {
            "id": "es-CO-SalomeNeural",
            "name": "Salomé (Agradable, empática y dulce)",
            "rate": "-2%",
            "pitch": "+0Hz"
        }
    }

    DEFAULT_VOICE_KEY = "elvira"

    def __init__(self, voice_key: Optional[str] = None, output_dir: Optional[str] = None, enabled: bool = True):
        self.voice_key = voice_key if voice_key in self.VOICES else self.DEFAULT_VOICE_KEY
        self.enabled = enabled
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.output_dir = Path(output_dir) if output_dir else base_dir / "data" / "audio"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._current_playback_thread: Optional[threading.Thread] = None

    @property
    def current_voice_info(self) -> Dict[str, str]:
        return self.VOICES.get(self.voice_key, self.VOICES[self.DEFAULT_VOICE_KEY])

    @property
    def voice(self) -> str:
        return self.current_voice_info["id"]

    def set_voice(self, key_or_id: str):
        """Cambia la voz activa por clave corta o ID."""
        key_or_id = key_or_id.lower().strip()
        for k, info in self.VOICES.items():
            if k == key_or_id or info["id"].lower() == key_or_id:
                self.voice_key = k
                return True
        return False

    def clean_text_for_speech(self, text: str) -> str:
        """
        Adapta el texto escrito a un lenguaje oral natural, fluido y expresivo.
        Omite código largo y tecnicismos no verbalizables, haciendo que suene humana.
        """
        if not text:
            return ""

        # Eliminar cadenas de pensamiento interno
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        
        # Si hay bloques de código, sustituirlos por una mención hablada natural
        if "```" in text:
            text = re.sub(r"```[a-zA-Z]*\n[\s\S]*?```", " Te he preparado el bloque de código correspondiente en pantalla. ", text)

        # Eliminar etiquetas markdown y formatos
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"https?://\S+", "enlace que ves en pantalla", text)
        text = re.sub(r"^[#*>\-\+]\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)

        # Suavizar signos y numeraciones para que suenen hablados
        text = re.sub(r"\n\d+\.\s+", ". En primer lugar, ", text, count=1)
        text = re.sub(r"\n\d+\.\s+", ". Por otra parte, ", text)
        text = re.sub(r"\n[-•]\s+", ", ", text)

        # Limpiar saltos de línea y múltiples espacios
        text = re.sub(r"\s+", " ", text).strip()

        # Evitar respuestas vocales excesivamente largas (locución de hasta ~350 palabras para ser ágil)
        words = text.split(" ")
        if len(words) > 80:
            # Tomar los párrafos principales para hablar y dejar el resto en pantalla
            shortened = " ".join(words[:75])
            # Cortar en el último punto
            last_period = shortened.rfind(".")
            if last_period > 30:
                shortened = shortened[:last_period + 1]
            text = shortened + " Te dejo todos los detalles completos por escrito en el panel."

        return text

    async def synthesize_async(self, text: str, filename: Optional[str] = None) -> Optional[str]:
        """Sintetiza texto con cadencia y tono natural."""
        clean = self.clean_text_for_speech(text)
        if not clean:
            return None

        if not filename:
            filename = f"edith_{uuid.uuid4().hex[:8]}.mp3"
        output_path = self.output_dir / filename

        voice_info = self.current_voice_info

        try:
            communicate = edge_tts.Communicate(
                text=clean,
                voice=voice_info["id"],
                rate=voice_info["rate"],
                pitch=voice_info["pitch"]
            )
            await communicate.save(str(output_path))
            return str(output_path)
        except Exception:
            return None

    def synthesize_sync(self, text: str, filename: Optional[str] = None) -> Optional[str]:
        try:
            return asyncio.run(self.synthesize_async(text, filename))
        except Exception:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.synthesize_async(text, filename))
            finally:
                loop.close()

    def play_audio(self, audio_path: str, block: bool = False):
        if not PYGAME_INITIALIZED or not os.path.exists(audio_path):
            return

        def _play():
            try:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()
                pygame.mixer.music.load(audio_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
            except Exception:
                pass

        if block:
            _play()
        else:
            self._current_playback_thread = threading.Thread(target=_play, daemon=True)
            self._current_playback_thread.start()

    def stop_audio(self):
        if PYGAME_INITIALIZED and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()

    def speak(self, text: str, block: bool = False) -> Optional[str]:
        if not self.enabled:
            return None
        audio_file = self.synthesize_sync(text)
        if audio_file:
            self.play_audio(audio_file, block=block)
        return audio_file


_default_voice_engine: Optional[VoiceEngine] = None

def get_voice_engine() -> VoiceEngine:
    global _default_voice_engine
    if _default_voice_engine is None:
        _default_voice_engine = VoiceEngine()
    return _default_voice_engine

def speak_async(text: str):
    engine = get_voice_engine()
    if engine.enabled:
        threading.Thread(target=engine.speak, args=(text, False), daemon=True).start()
