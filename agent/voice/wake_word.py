"""Palabra de activación «Oye EDITH».

La interfaz capta el micrófono, separa los tramos con voz y los manda a EDITH; aquí se transcriben
con Whisper EN LOCAL (faster-whisper, el mismo motor que las notas de voz) y se decide si alguien
llamó a EDITH. Antes se usaba el reconocimiento de voz del navegador (Web Speech API), que dentro
de la app de escritorio (WebView2) no funciona: falla con «network» al segundo de arrancar.

Reglas para no activarse por error:
- El nombre tiene que ir al principio de la frase, solo o tras un saludo («oye», «hey», «hola»…):
  «Hola, soy EDITH» (la propia EDITH hablando) o «le dije a Edith» no la despiertan.
- Palabras parecidas que no son el nombre («editar», «edita», «Meredith», «crédito») no cuentan.
"""

import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from ..config import Config

# Frases que activan a EDITH (informativo; la detección real está en WakeWordDetector.match)
WAKE_WORDS = ["oye edith", "hey edith", "hola edith", "edith"]

NAME = "edith"
# Cómo suele escribir Whisper el nombre (en español lo oye a menudo como «edit»)
NAME_FORMS = {"edith", "edit", "edyth", "editt", "eddith", "idith"}
# Lo que también escribe cuando el nombre se oye peor (sensibilidad normal y alta)
NAME_WEAK = {"dit", "edi", "edic", "edid", "edis", "ediz", "eddie", "edie", "yedi"}
# Parecidas al nombre, pero son otras palabras
NOT_NAME = {
    "edita", "editas", "editan", "editar", "editara", "editado", "editada", "editados", "editadas", "edito",
    "editor", "editora", "editores", "editorial", "edicion", "ediciones", "editen", "edite", "edits",
    "credito", "creditos", "meredith", "judith", "edicto", "edil", "edifico", "edificio", "inedito",
}
# Lo que puede ir antes del nombre sin que deje de ser una llamada («oye, EDITH», «buenos días, EDITH»)
GREETINGS = {
    "oye", "oyes", "oiga", "oigan", "hey", "ey", "ei", "eh", "oh", "hei", "hola", "ola", "alo", "ok", "okay",
    "okey", "vale", "buenas", "buenos", "buen", "dias", "tardes", "noches", "que", "hay", "tal",
}
# Una orden empieza con un verbo o una pregunta («abre», «pon», «¿qué…?»), no con un artículo. Si tras
# el «nombre» viene «la foto», en realidad era «edita la foto» (con la pista y ruido, Whisper lo escribe
# «EDITH, la foto…»)
ARTICLES = {
    "el", "la", "los", "las", "lo", "un", "una", "unos", "unas", "ese", "esa", "esos", "esas",
    "este", "esta", "estos", "estas", "aquel", "aquella", "mi", "mis", "tu", "tus", "su", "sus", "al", "del",
}
# Textos que Whisper «oye» en el ruido o el silencio
HALLUCINATIONS = (
    "subtitulos realizados por la comunidad de amara org", "subtitulos por la comunidad de amara org",
    "gracias por ver el video", "gracias por ver", "suscribete", "no olvides suscribirte", "musica",
    "gracias", "amara org",
)

# Sensibilidad. before: saludos permitidos antes del nombre; weak: aceptar las formas débiles del
# nombre; ratio: similitud mínima con «edith» para otras palabras; alone: el nombre tiene que ir solo
# («Oye EDITH», pitido, y luego la orden), así una frase que empieza parecido nunca la despierta
SENSITIVITY = {
    "baja": {"before": 2, "weak": False, "ratio": 1.0, "alone": True},
    "normal": {"before": 3, "weak": True, "ratio": 0.8, "alone": False},
    "alta": {"before": 4, "weak": True, "ratio": 0.66, "alone": False},  # micrófonos lejanos o voz baja
}

# Pista para Whisper: sin ella escribe el nombre como «dit», «edic» o «Eddie» y se pierde la mitad
# de las llamadas (medido con 184 frases sintetizadas: «Registro de Cambios de EDITH», v0.0.10)
WAKE_PROMPT = "Oye EDITH, hola EDITH."
# A veces Whisper copia la pista en vez de la orden («Hey EDITH, ¿qué hora es?» -> «Hey EDITH, hola EDITH»)
_PROMPT_LEAK = re.compile(r"[,.]?\s*\b(?:oye|hola)\s*,?\s*edith\b[.!]?", re.IGNORECASE)
# Un «EDITH» suelto con demasiada voz no es una llamada: guiado por la pista y con ruido, Whisper
# ha llegado a convertir «Edita la foto y mándamela» en «EDITH.». Segundos de voz (sin márgenes)
# para el nombre solo, más un poco por cada saludo delante («oye», «hola»)
MAX_NAME_ONLY_SECONDS = 1.0
SECONDS_PER_GREETING = 0.5

SAMPLE_RATE = 16000
MAX_SECONDS = 15


def normalize(word: str) -> str:
    """Minúsculas, sin tildes ni signos: «¡EDITH!» -> «edith»."""
    w = unicodedata.normalize("NFD", word.lower())
    w = "".join(c for c in w if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", w)


def _words(text: str) -> List[Tuple[str, str]]:
    """(palabra original, palabra normalizada). «E.D.I.T.H.» cuenta como «EDITH»."""
    text = re.sub(r"(?<=\b\w)\.(?=\w\b)", "", text or "")
    out = []
    for raw in re.split(r"[\s,;:—–\-]+", text):
        n = normalize(raw)
        if n:
            out.append((raw, n))
    return out


def is_hallucination(text: str) -> bool:
    clean = " ".join(normalize(w) for w in re.split(r"[\s.,;:!?¡¿]+", text or "") if normalize(w))
    return not clean or clean in HALLUCINATIONS


@dataclass
class WakeMatch:
    wake: bool
    command: str = ""


class WakeWordDetector:
    """Decide si una frase transcrita llama a EDITH y separa la orden que viene detrás."""

    def __init__(self, sensitivity: Optional[str] = None):
        self.sensitivity = sensitivity

    @property
    def level(self) -> str:
        s = (self.sensitivity or getattr(Config, "WAKE_WORD_SENSITIVITY", "normal") or "normal").lower()
        return s if s in SENSITIVITY else "normal"

    def is_name(self, word: str) -> bool:
        if word in NOT_NAME:
            return False
        if word in NAME_FORMS:
            return True
        opts = SENSITIVITY[self.level]
        if opts["weak"] and word in NAME_WEAK:
            return True
        return opts["ratio"] < 1.0 and len(word) >= 4 and SequenceMatcher(None, word, NAME).ratio() >= opts["ratio"]

    def match(self, text: str, speech_seconds: Optional[float] = None) -> WakeMatch:
        """`speech_seconds`: segundos con voz del tramo, sin márgenes. Si se da, un «EDITH» sin orden
        detrás que ocupa demasiada voz no cuenta (ver MAX_NAME_ONLY_SECONDS)."""
        words = _words(text)
        opts = SENSITIVITY[self.level]
        for i, (_raw, norm) in enumerate(words[:opts["before"] + 1]):
            if self.is_name(norm):
                if not all(w in GREETINGS for _, w in words[:i]):
                    return WakeMatch(False)
                rest = " ".join(raw for raw, _ in words[i + 1:])
                if _PROMPT_LEAK.search(rest):
                    return WakeMatch(True, "")  # la orden se perdió: EDITH se queda escuchando para oírla
                command = rest.strip(" ,.;:!-—").strip()
                if command and (opts["alone"] or words[i + 1][1] in ARTICLES):
                    return WakeMatch(False)
                if (not command and speech_seconds
                        and speech_seconds > MAX_NAME_ONLY_SECONDS + SECONDS_PER_GREETING * i):
                    return WakeMatch(False)
                return WakeMatch(True, command)
            if norm not in GREETINGS:
                return WakeMatch(False)  # la frase empieza con otra cosa: no es una llamada
        return WakeMatch(False)

    def is_wake_phrase(self, text: str) -> bool:
        return self.match(text).wake

    def extract_command_after_wake(self, text: str) -> str:
        m = self.match(text)
        return m.command if m.wake else (text or "").strip()


_global_wake_detector: Optional[WakeWordDetector] = None


def get_wake_detector() -> WakeWordDetector:
    global _global_wake_detector
    if _global_wake_detector is None:
        _global_wake_detector = WakeWordDetector()
    return _global_wake_detector


# ---------------------------------------------------------------- transcripción local
class WakeListener:
    """Modelo Whisper para «Oye EDITH»: se carga en segundo plano y transcribe tramos cortos de voz."""

    def __init__(self):
        self._model = None
        self._model_name = None
        self._lock = threading.Lock()          # carga del modelo
        self._busy = threading.Semaphore(1)    # una transcripción a la vez: no saturar la CPU
        self.loading = False
        self.error = ""

    def _wanted_model(self) -> str:
        return getattr(Config, "WAKE_WORD_MODEL", "base") or "base"

    def _load(self):
        name = self._wanted_model()
        with self._lock:
            if self._model is not None and self._model_name == name:
                return self._model
            self.loading = True
            try:
                if name == Config.WHISPER_MODEL:  # el mismo que las notas de voz: un solo modelo en memoria
                    from ..channels.voice_notes import _whisper
                    self._model = _whisper()
                else:
                    from faster_whisper import WhisperModel  # import perezoso: tarda y pesa
                    self._model = WhisperModel(name, device=Config.WHISPER_DEVICE,
                                               compute_type=Config.WHISPER_COMPUTE_TYPE)
                self._model_name = name
                self.error = ""
                return self._model
            except Exception as exc:  # sin internet la primera vez, disco lleno…
                self.error = f"No pude cargar el modelo de voz «{name}»: {exc}"
                raise
            finally:
                self.loading = False

    @property
    def ready(self) -> bool:
        return self._model is not None and self._model_name == self._wanted_model()

    def prepare(self):
        """Carga el modelo en segundo plano (la primera vez lo descarga)."""
        if self.ready or self.loading:
            return
        self.loading = True
        threading.Thread(target=self._safe_load, daemon=True).start()

    def _safe_load(self):
        try:
            self._load()
        except Exception:
            pass

    def reset(self):
        """Tras cambiar WAKE_WORD_MODEL en Ajustes."""
        with self._lock:
            self._model = None
            self._model_name = None

    def status(self) -> dict:
        return {"enabled": bool(getattr(Config, "WAKE_WORD_ENABLED", True)),
                "sensitivity": get_wake_detector().level, "model": self._wanted_model(),
                "ready": self.ready, "loading": self.loading, "error": self.error}

    @staticmethod
    def pcm16_to_float(pcm: bytes):
        import numpy as np
        if len(pcm) % 2:
            pcm = pcm[:-1]
        return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0

    def transcribe(self, samples, mode: str = "wake") -> Optional[str]:
        """None = ocupado con otro tramo: en modo activación se descarta en vez de hacer cola (la orden
        que sigue a «Oye EDITH» sí espera su turno)."""
        wait = mode == "command"
        if not (self._busy.acquire(timeout=20) if wait else self._busy.acquire(blocking=False)):
            return None
        try:
            model = self._load()
            prompt = WAKE_PROMPT if mode == "wake" else None  # la pista solo al buscar el nombre
            segments, _info = model.transcribe(
                samples, language="es", beam_size=1, temperature=0.0, vad_filter=True,
                condition_on_previous_text=False, without_timestamps=True, initial_prompt=prompt)
            text = " ".join(s.text.strip() for s in segments).strip()
            return "" if is_hallucination(text) else text
        finally:
            self._busy.release()

    @staticmethod
    def speech_seconds(samples) -> float:
        """Segundos con voz según Silero (el filtro de faster-whisper), sin los márgenes que añade al transcribir."""
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        spans = get_speech_timestamps(samples, VadOptions(speech_pad_ms=0, min_silence_duration_ms=150))
        return sum(s["end"] - s["start"] for s in spans) / SAMPLE_RATE

    def listen(self, pcm: bytes, mode: str = "wake") -> dict:
        """Un tramo de voz (PCM 16 bits, mono, 16 kHz) -> {"text", "wake", "command"}."""
        t0 = time.perf_counter()
        samples = self.pcm16_to_float(pcm)
        if samples.size < SAMPLE_RATE * 0.25:  # menos de 1/4 s: un golpe o un clic
            return {"text": "", "wake": False, "command": "", "ms": 0}
        text = self.transcribe(samples, mode)
        if text is None:
            return {"text": "", "wake": False, "command": "", "busy": True, "ms": 0}
        if mode == "command":
            return {"text": text, "wake": False, "command": text, "ms": int((time.perf_counter() - t0) * 1000)}
        detector = get_wake_detector()
        m = detector.match(text)
        if m.wake and not m.command:  # solo el nombre: ¿cabe en la voz que hubo?
            m = detector.match(text, self.speech_seconds(samples))
        return {"text": text, "wake": m.wake, "command": m.command, "ms": int((time.perf_counter() - t0) * 1000)}


_listener: Optional[WakeListener] = None


def get_wake_listener() -> WakeListener:
    global _listener
    if _listener is None:
        _listener = WakeListener()
    return _listener
