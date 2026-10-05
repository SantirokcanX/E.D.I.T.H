"""Voice package for EDITH: Natural Speech Synthesis and Wake Word Detection."""

from .voice_engine import VoiceEngine, get_voice_engine, speak_async
from .wake_word import WakeWordDetector, get_wake_detector, WAKE_WORDS

__all__ = [
    "VoiceEngine",
    "get_voice_engine",
    "speak_async",
    "WakeWordDetector",
    "get_wake_detector",
    "WAKE_WORDS"
]
