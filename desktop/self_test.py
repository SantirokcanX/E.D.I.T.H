"""Autocomprobación del paquete (Fase 15.3): EDITH.exe --self-test[=informe.txt]

Comprueba, sin abrir ventanas ni el icono de la bandeja, que el ejecutable de PyInstaller trae
todo lo que EDITH necesita: interfaz, iconos, servidor, dependencias pesadas (numpy, scikit-learn,
faster-whisper/ctranslate2, onnxruntime, PyAV, pygame, edge-tts), pywebview/pythonnet, pystray y
la voz local de Windows (SAPI5). La usa build/build_setup.ps1 justo después de construir.

Usar SIEMPRE con EDITH_HOME apuntando a una carpeta temporal: importa el servidor como al arrancar.
Devuelve 0 si todo está bien y 1 si algo falla; el informe va al archivo indicado (o a logs/).
"""

import io
import math
import os
import struct
import time
import traceback
import wave
from pathlib import Path


def _wav_tone(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


def run(report_path: Path) -> int:
    os.environ.setdefault("OLLAMA_WARMUP", "false")  # sin precargar el modelo
    from agent.paths import APP_DIR, EDITH_HOME, FROZEN, VERSION

    results = []

    def probe(name, fn):
        start = time.perf_counter()
        try:
            detail = fn()
            results.append((True, name, detail or ""))
        except Exception as e:  # noqa: BLE001  (el informe recoge cualquier fallo)
            results.append((False, name, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"))
        results[-1] = (*results[-1], time.perf_counter() - start)

    def version():
        assert VERSION != "0.0.0", "no se encontró el archivo VERSION"
        return VERSION

    def resources():
        needed = ["ide/static/index.html", "ide/static/app.js", "ide/static/setup.js", "ide/static/render.js",
                  "ide/static/styles.css", "ide/static/logo.png", "ide/static/favicon.ico",
                  "desktop/assets/edith-app.ico", "desktop/assets/edith-tray.png", "VERSION"]
        missing = [p for p in needed if not (APP_DIR / p).is_file()]
        assert not missing, f"faltan: {missing}"
        return f"{len(needed)} archivos en {APP_DIR}"

    def server():
        from fastapi.testclient import TestClient
        from agent.channels.security import get_api_token
        import ide.server as srv
        client = TestClient(srv.app, base_url="http://127.0.0.1:8000")
        auth = {"Authorization": f"Bearer {get_api_token()}"}
        r = client.get("/api/version", headers=auth)
        assert r.status_code == 200 and r.json()["version"] == VERSION, (r.status_code, r.text[:200])
        page = client.get("/", headers=auth)
        assert page.status_code == 200 and f"app.js?v={VERSION}" in page.text, page.status_code
        setup = client.get("/api/setup/status", headers=auth).json()
        return f"API y página principal OK · asistente completado={setup['completed']} · ML={'sí' if srv.ml_engine else 'no'}"

    def whatsapp_bridge():  # opcional: solo informa
        from ide.channels_api import BRIDGE_EXE, bridge_command
        cmd = bridge_command()
        if not cmd:
            return f"no instalado (es opcional): falta {BRIDGE_EXE.name}"
        return f"{' '.join(Path(c).name for c in cmd[0])} en {cmd[1]}"

    def scientific():
        import numpy as np
        from sklearn.feature_extraction.text import HashingVectorizer
        from sklearn.linear_model import SGDClassifier
        x = HashingVectorizer(n_features=2 ** 10).transform(["hola edith", "calcula la integral"])
        SGDClassifier().partial_fit(x, [0, 1], classes=np.array([0, 1]))
        import scipy
        return f"numpy {np.__version__}, scipy {scipy.__version__}"

    def whisper():
        import ctranslate2
        from faster_whisper.vad import get_vad_model
        get_vad_model()  # carga silero_vad (asset de faster-whisper) con onnxruntime
        return f"ctranslate2 {ctranslate2.__version__} · CPU: {sorted(ctranslate2.get_supported_compute_types('cpu'))}"

    def audio():
        from agent.channels import voice_notes
        ogg = voice_notes.to_ogg_opus(_wav_tone())
        samples = voice_notes.decode_16k_mono(ogg)
        assert ogg[:4] == b"OggS" and len(samples) > 4000, (ogg[:4], len(samples))
        import av
        return f"PyAV {av.__version__}: WAV -> OGG/Opus ({len(ogg)} bytes) -> 16 kHz"

    def sound_and_voice():
        import edge_tts
        import pygame
        from agent.voice import voice_engine
        return f"pygame {pygame.version.ver} (mixer={'sí' if voice_engine.PYGAME_INITIALIZED else 'no'}), edge-tts {edge_tts.__version__}"

    def sapi5():
        from agent.voice.voice_engine import VoiceEngine
        out = EDITH_HOME / "self-test-sapi5.wav"
        path = VoiceEngine.synthesize_offline("Prueba de voz de EDITH.", out)
        assert path, "System.Speech no generó audio (¿hay voces instaladas?)"
        size = out.stat().st_size
        out.unlink(missing_ok=True)
        return f"{size} bytes"

    def desktop():
        import clr  # noqa: F401  (pythonnet)
        import pystray
        import webview
        from webview.platforms import winforms  # noqa: F401  (WebView2 + WinForms)
        from Microsoft.Win32 import SystemEvents  # noqa: F401
        return f"WebView2 (WinForms) y pythonnet cargados · bandeja: {pystray.Icon.__module__}"

    def others():
        import bs4  # noqa: F401
        import ddgs  # noqa: F401
        import google.genai  # noqa: F401
        import ollama  # noqa: F401
        import psutil
        import twilio.rest  # noqa: F401
        from PIL import Image  # noqa: F401
        return f"psutil {psutil.__version__}"

    for name, fn in [("versión", version), ("recursos", resources), ("servidor", server),
                     ("bridge de WhatsApp", whatsapp_bridge), ("numpy/scikit-learn", scientific), ("faster-whisper", whisper), ("PyAV (notas de voz)", audio),
                     ("pygame/edge-tts", sound_and_voice), ("voz de Windows (SAPI5)", sapi5),
                     ("ventana y bandeja", desktop), ("otras dependencias", others)]:
        probe(name, fn)

    ok = all(r[0] for r in results)
    lines = [f"EDITH {VERSION} · autocomprobación · {'EMPAQUETADA' if FROZEN else 'desde el código'} · datos: {EDITH_HOME}"]
    lines += [f"[{'OK ' if good else 'FALLO'}] {name} ({secs:.1f} s): {detail}".rstrip() for good, name, detail, secs in results]
    lines.append(f"{sum(r[0] for r in results)}/{len(results)} comprobaciones OK")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1
