"""Pruebas de la voz de EDITH: voces distintas, voz «Viernes» y la palabra de activación «Oye EDITH».

Qué estaba roto y qué se comprueba aquí:
1. Todas las voces sonaban igual: edge-tts 7.2.8 recibía un 403 de Microsoft (cambió el token
   Sec-MS-GEC) y EDITH caía en silencio en la voz SAPI5 de Windows, la misma para todas. Se generan
   muestras reales por la ruta de Ajustes y se comparan la voz neural usada, el audio y el tono.
2. La voz «Viernes»: multilingüe, femenina, y que se entienda en español (se transcribe con Whisper).
3. «Oye EDITH»: el reconocimiento del navegador no funciona en WebView2 y la frase se buscaba como
   subcadena («edit» saltaba con «editar»). Se mide el detector nuevo con audio sintetizado por varias
   voces (activaciones y falsos positivos) y se compara con la regla antigua sobre las mismas frases.

Necesita internet (voces de Microsoft) y descarga Whisper «base» la primera vez (145 MB).
Uso:  python tests/test_voz.py   (desde la raíz del proyecto, con el .venv activado)
"""
import asyncio
import hashlib
import os
import time
from difflib import SequenceMatcher
from pathlib import Path

os.environ["ML_ENABLED"] = "false"
os.environ["WAKE_WORD_MODEL"] = "base"
os.environ["WAKE_WORD_SENSITIVITY"] = "normal"
os.environ.pop("EDITH_VOICE", None)
from entorno import TMP, Config, check, sec, summary  # noqa: E402

import agent.config as config_module  # noqa: E402
ENV = TMP / "voz.env"
ENV.write_text("# pruebas de voz\n", encoding="utf-8")
config_module.env_path = ENV
Config.reload()

import edge_tts  # noqa: E402
import numpy as np  # noqa: E402
from dotenv import dotenv_values  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import ide.server as srv  # noqa: E402
from agent.channels.voice_notes import decode_16k_mono  # noqa: E402
from agent.setup import settings  # noqa: E402
from agent.voice import voice_engine as ve  # noqa: E402
from agent.voice.voice_engine import VoiceEngine  # noqa: E402
from agent.voice.wake_word import WakeWordDetector, get_wake_listener, is_hallucination, normalize  # noqa: E402

TOKEN = sec.get_api_token()
BASE = "http://127.0.0.1:8000"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
POST = {**AUTH, "Origin": BASE}
client = TestClient(srv.app, base_url=BASE)
OLD_WAKE_WORDS = ["edith", "oye edith", "hey edith", "hola edith", "edit", "oye edit"]  # regla de antes


def old_rule(text: str) -> bool:
    """Lo que hacían app.js y wake_word.py antes: buscar cualquiera de las palabras como subcadena."""
    return any(w in text.lower().strip() for w in OLD_WAKE_WORDS)


def median_pitch(samples: np.ndarray, rate: int = 16000) -> float:
    """Tono medio (Hz) por autocorrelación en tramos con voz: para comparar voces, no para afinar."""
    frame, pitches = int(rate * 0.04), []
    for i in range(0, len(samples) - frame, frame):
        x = samples[i:i + frame] - samples[i:i + frame].mean()
        if np.sqrt(np.mean(x ** 2)) < 0.02:
            continue
        ac = np.correlate(x, x, "full")[frame - 1:]
        lo, hi = rate // 400, rate // 70  # entre 70 y 400 Hz
        lag = lo + int(np.argmax(ac[lo:hi]))
        if ac[lag] > 0.3 * ac[0]:
            pitches.append(rate / lag)
    return float(np.median(pitches)) if pitches else 0.0


def pcm16(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()


# ======================= 1. Causa: la versión de edge-tts =======================
version = tuple(int(p) for p in edge_tts.__version__.split(".")[:3])
check("edge-tts >= 7.3.1 (la 7.2.8 recibe 403 de Microsoft en todas las voces)", version >= (7, 3, 1), edge_tts.__version__)
req = Path(__file__).resolve().parent.parent / "requirements.txt"
check("requirements.txt pide edge-tts>=7.3.1", "edge-tts>=7.3.1" in req.read_text(encoding="utf-8"))

# ======================= 2. Catálogo de voces =======================
keys = list(VoiceEngine.VOICES)
check("Ajustes y el motor ofrecen las mismas voces (incluida «viernes»)",
      [k for k, _ in settings.VOICE_CHOICES] == keys and "viernes" in keys, keys)
ids = [v["id"] for v in VoiceEngine.VOICES.values()]
check("cada voz usa una voz neural distinta", len(set(ids)) == len(ids), ids)
schema_voice = next(f for s in settings.SCHEMA for f in s["fields"] if f["key"] == "EDITH_VOICE")
check("el asistente y Ajustes muestran «Viernes»", any(k == "viernes" for k, _ in schema_voice["options"]))
check("se puede guardar EDITH_VOICE=viernes", settings._validate("EDITH_VOICE", "viernes") == ("viernes", None))
e = VoiceEngine(voice_key=None)
check("sin EDITH_VOICE la voz es Elvira", e.voice_key == "elvira")
check("set_voice acepta clave o ID", e.set_voice("VIERNES") and e.voice_key == "viernes"
      and e.set_voice("es-MX-DaliaNeural") and e.voice_key == "dalia" and not e.set_voice("inventada"))

try:
    catalog = {v["ShortName"]: v for v in asyncio.run(edge_tts.list_voices())}
except Exception as exc:  # sin red
    catalog = {}
    print("  (sin conexión con el catálogo de voces de Microsoft:", exc, ")")
check("todas las voces existen en el catálogo de Microsoft", catalog and all(i in catalog for i in ids),
      [i for i in ids if i not in catalog])
viernes_id = VoiceEngine.VOICES["viernes"]["id"]
check("«Viernes» es una voz femenina multilingüe (habla español)", catalog.get(viernes_id, {}).get("Gender") == "Female"
      and "Multilingual" in viernes_id, viernes_id)

# ======================= 3. Muestras reales desde Ajustes =======================
samples = {}
for key in keys:
    t0 = time.time()
    r = client.post("/api/setup/voice/sample", json={"voice_key": key}, headers=POST)
    d = r.json() if r.status_code == 200 else {"detail": r.text}
    ok = r.status_code == 200 and not d.get("offline") and d.get("voice_id") == VoiceEngine.VOICES[key]["id"]
    audio = client.get(d.get("audio_url", "/api/audio/nada"), headers=AUTH)
    ok = ok and audio.status_code == 200 and audio.headers["content-type"] == "audio/mpeg" and len(audio.content) > 5000
    check(f"muestra de «{key}» con su voz neural ({VoiceEngine.VOICES[key]['id']})", ok,
          f"{len(audio.content)} bytes en {time.time() - t0:.1f}s" if ok else d)
    if ok:
        pcm = decode_16k_mono(audio.content)
        samples[key] = {"sha": hashlib.sha1(audio.content).hexdigest(), "pcm": pcm,
                        "dur": len(pcm) / 16000, "f0": median_pitch(pcm)}
print("   voz      duración   tono medio")
for key, s in samples.items():
    print(f"   {key:8s} {s['dur']:5.2f} s   {s['f0']:6.1f} Hz")
check("las cinco muestras son audios distintos", len({s["sha"] for s in samples.values()}) == len(keys) == len(samples))
pairs = [(a, b) for i, a in enumerate(samples) for b in list(samples)[i + 1:]]
check("y suenan distinto: cada par difiere en tono (>4 Hz) o en duración (>0,15 s)",
      samples and all(abs(samples[a]["f0"] - samples[b]["f0"]) > 4 or abs(samples[a]["dur"] - samples[b]["dur"]) > 0.15
                      for a, b in pairs),
      [(a, b) for a, b in pairs if abs(samples[a]["f0"] - samples[b]["f0"]) <= 4
       and abs(samples[a]["dur"] - samples[b]["dur"]) <= 0.15])

# «Viernes» habla bien español: Whisper la transcribe casi palabra por palabra
listener = get_wake_listener()
if "viernes" in samples:
    model = listener._load()
    segs, info = model.transcribe(samples["viernes"]["pcm"], beam_size=1)
    heard = " ".join(s.text for s in segs)
    expected = "hola soy edith asi sonaria mi voz cuando hablemos"
    words = [normalize(w) for w in heard.split() if normalize(w)]
    hits = sum(w in words for w in expected.split())
    check("«Viernes» se entiende en español (Whisper detecta español y la frase)",
          info.language == "es" and hits >= 7, f"idioma={info.language} «{heard.strip()}»")

# ======================= 4. Si falla la voz neural: se dice por qué =======================
class FakeHandshake(Exception):
    status = 403


async def rejected(self, *a, **k):
    raise FakeHandshake("Invalid response status")

real_save = edge_tts.Communicate.save
edge_tts.Communicate.save = rejected
try:
    r = client.post("/api/setup/voice/sample", json={"voice_key": "dalia"}, headers=POST)
    d = r.json()
    check("con un 403, la muestra cae en la voz de Windows y lo dice", r.status_code == 200 and d["offline"]
          and "403" in d["reason"] and d["audio_url"].endswith(".wav"), d)
    Config.VOICE_OFFLINE_FALLBACK = False
    r = client.post("/api/setup/voice/sample", json={"voice_key": "dalia"}, headers=POST)
    check("sin respaldo, el error explica el motivo (antes: «No pude generar la muestra»)",
          r.status_code == 503 and "403" in r.json()["detail"], r.json())
    Config.VOICE_OFFLINE_FALLBACK = True
finally:
    edge_tts.Communicate.save = real_save
check("motivos legibles: tiempo agotado y sin conexión",
      "tardó" in VoiceEngine.describe_error(asyncio.TimeoutError())
      and "Sin conexión" in VoiceEngine.describe_error(ConnectionRefusedError()))
wav = VoiceEngine.synthesize_offline("Prueba de voz de Windows.", TMP / "sapi_mx.wav", "es-MX")
check("respaldo SAPI5 con la región de la voz (es-MX)", bool(wav) and Path(wav).stat().st_size > 1000)

# ======================= 5. Elegir la voz se aplica y se guarda =======================
r = client.post("/api/voice/select", json={"voice_key": "viernes"}, headers=POST)
check("el selector de la barra lateral cambia la voz al momento", r.status_code == 200
      and srv.voice_engine.voice_key == "viernes", r.json())
check("...y la guarda en el .env (antes se perdía al reiniciar)", r.json().get("saved")
      and dotenv_values(ENV).get("EDITH_VOICE") == "viernes", ENV.read_text(encoding="utf-8"))
r = client.post("/api/voice/select", json={"voice_key": "dalia"}, headers={**AUTH, "Origin": "http://sitio-ajeno.example"})
check("otra web no puede cambiarla", r.status_code == 403 and dotenv_values(ENV).get("EDITH_VOICE") == "viernes")
st = client.get("/api/status", headers=AUTH).json()
check("/api/status lista las cinco voces para la barra lateral", [v["key"] for v in st["available_voices"]] == keys)
r = client.post("/api/settings", json={"values": {"EDITH_VOICE": "salome"}}, headers=POST)
check("Ajustes › Voz aplica la voz sin reiniciar", r.status_code == 200 and "voz" in r.json()["applied"]
      and srv.voice_engine.voice_key == "salome")

# ======================= 6. «Oye EDITH»: reglas =======================
det = WakeWordDetector("normal")
calls = {
    "Oye EDITH, abre la calculadora": "abre la calculadora",
    "Hey Edith, ¿qué hora es?": "¿qué hora es?",
    "EDITH, pon música relajante.": "pon música relajante",
    "Oye, Edith.": "",
    "Buenos días, EDITH": "",
    "¿Qué hay, EDITH?": "",
    "E.D.I.T.H. abre el navegador": "abre el navegador",
    "Oye dit, abre la calculadora": "abre la calculadora",  # Whisper oye «dit»
}
for text, cmd in calls.items():
    m = det.match(text)
    check(f"llamada: «{text}»", m.wake and m.command == cmd.rstrip("."), (m.wake, m.command))
not_calls = ["Voy a editar el documento antes de enviarlo", "Hola, soy EDITH. ¿En qué te puedo ayudar?",
             "Ayer hablé con Edith sobre el proyecto", "Meredith llegó tarde a la reunión",
             "La editorial publicó el libro", "Edita la foto y mándamela", "Le dije a EDITH que esperara",
             "Oye, ¿me pasas el control remoto?", "Es una edición especial", ""]
for text in not_calls:
    check(f"no es una llamada: «{text}»" + (" (la regla antigua sí saltaba)" if old_rule(text) else ""),
          not det.match(text).wake)
check("la regla antigua saltaba con la propia voz de EDITH y con «editar»",
      old_rule("Hola, soy EDITH. ¿En qué te puedo ayudar?") and old_rule("Voy a editar el documento"))
check("pista copiada en vez de la orden -> se queda escuchando la orden",
      det.match("Hei EDITH, que hola EDITH.").wake and det.match("Hei EDITH, que hola EDITH.").command == "")
check("un «EDITH.» suelto con 1,6 s de voz no cuenta (era «Edita la foto…» con ruido)",
      not det.match("EDITH.", speech_seconds=1.6).wake and det.match("EDITH.", speech_seconds=0.45).wake
      and det.match("Oye, EDITH.", speech_seconds=1.2).wake)
low = WakeWordDetector("baja")
check("sensibilidad baja: solo el nombre a secas (y sin formas dudosas)",
      low.match("Oye EDITH").wake and not low.match("Oye EDITH, abre la calculadora").wake
      and not low.match("Oye dit").wake)
high = WakeWordDetector("alta")
check("sensibilidad alta: acepta nombres peor oídos («Edet»), la normal no", high.match("Oye Edet, abre Spotify").wake
      and not det.match("Oye Edet, abre Spotify").wake)
check("se descartan las alucinaciones típicas de Whisper", is_hallucination("Subtítulos realizados por la comunidad de Amara.org")
      and is_hallucination("") and not is_hallucination("Oye EDITH"))

# ======================= 7. «Oye EDITH»: rutas =======================
static = client.get("/wake-worklet.js", headers=AUTH)
check("la interfaz sirve el procesador de micrófono", static.status_code == 200 and "registerProcessor" in static.text)
app_js = client.get("/app.js", headers=AUTH).text
check("app.js ya no usa el reconocimiento del navegador (no funciona en WebView2)",
      "SpeechRecognition" not in app_js and "/api/voice/wake/listen" in app_js)
st = client.get("/api/voice/wake/status", headers=AUTH).json()
check("estado: activo, sensibilidad normal, modelo base", st["enabled"] and st["sensitivity"] == "normal" and st["model"] == "base", st)
r = client.post("/api/voice/wake/prepare", headers=POST).json()
t0 = time.time()
while not client.get("/api/voice/wake/status", headers=AUTH).json()["ready"] and time.time() - t0 < 600:
    time.sleep(0.5)
check("el modelo se prepara en segundo plano", client.get("/api/voice/wake/status", headers=AUTH).json()["ready"])
r = client.post("/api/voice/wake/listen", content=b"\0" * (16000 * 2 * 16), headers=POST)
check("un tramo de más de 15 s se rechaza (413)", r.status_code == 413)
r = client.post("/api/voice/wake/listen", content=b"\0" * 32000, headers={**AUTH, "Origin": "http://sitio-ajeno.example"})
check("otra web no puede mandar audio", r.status_code == 403)
check("sin token tampoco", client.post("/api/voice/wake/listen", content=b"\0" * 32000).status_code == 401)
r = client.post("/api/voice/wake/listen", content=b"\0" * 32000, headers=POST).json()
check("silencio -> nada", not r["wake"] and not r["text"], r)
Config.WAKE_WORD_ENABLED = False
r1 = client.post("/api/voice/wake/listen", content=b"\0" * 32000, headers=POST)
r2 = client.post("/api/voice/wake/listen?mode=command", content=b"\0" * 32000, headers=POST)
check("desactivado en Ajustes: no escucha la palabra, pero el botón 🎙️ sí dicta", r1.status_code == 409 and r2.status_code == 200)
Config.WAKE_WORD_ENABLED = True
listener._busy.acquire()
try:
    t0 = time.time()
    r = client.post("/api/voice/wake/listen", content=pcm16(np.random.default_rng(1).normal(0, 0.1, 16000).astype(np.float32)),
                    headers=POST).json()
    check("si ya está transcribiendo otro tramo, no hace cola (no satura la CPU)", r.get("busy") and time.time() - t0 < 1, r)
finally:
    listener._busy.release()

# ======================= 8. «Oye EDITH» con audio real =======================
VOICES = ["es-MX-JorgeNeural", "es-ES-AlvaroNeural", "es-MX-DaliaNeural", "es-CO-SalomeNeural"]
POSITIVES = [("Oye EDITH", ""), ("Oye EDITH, abre la calculadora", "abre la calculadora"),
             ("EDITH, pon música relajante", "pon música relajante"), ("Hola EDITH", "")]
NEGATIVES = ["Voy a editar el documento antes de enviarlo", "Meredith llegó tarde a la reunión",
             "Edita la foto y mándamela", "Hola, soy EDITH. ¿En qué te puedo ayudar?",
             "Ayer hablé con Edith sobre el proyecto", "La editorial publicó el libro ayer"]
clips = TMP / "clips"
clips.mkdir()


async def make_clips():
    sem = asyncio.Semaphore(6)

    async def one(path, text, voice):
        async with sem:
            for _ in range(3):
                try:
                    await edge_tts.Communicate(text, voice).save(str(path))
                    return
                except Exception:
                    await asyncio.sleep(1)

    jobs = []
    for v in VOICES:
        for i, (t, _) in enumerate(POSITIVES):
            jobs.append(one(clips / f"p{i}_{v}.mp3", t, v))
        for i, t in enumerate(NEGATIVES):
            jobs.append(one(clips / f"n{i}_{v}.mp3", t, v))
    await asyncio.gather(*jobs)

asyncio.run(make_clips())
rng = np.random.default_rng(7)


def listen(path: Path, noisy: bool):
    x = decode_16k_mono(path.read_bytes())
    pad = np.zeros(4800, np.float32)  # el detector de la interfaz manda 0,3 s antes y después
    x = np.concatenate([pad, x, pad])
    if noisy:  # ruido a 10 dB por debajo de la voz
        n = rng.normal(0, 1, x.size).astype(np.float32)
        x = x + n * np.sqrt(np.mean(x ** 2) / 10 / np.mean(n ** 2))
    return client.post("/api/voice/wake/listen", content=pcm16(x), headers=POST).json()


lat = []
for noisy in (False, True):
    hit = cmd_ok = fp = fp_old = 0
    misses = []
    for v in VOICES:
        for i, (text, cmd) in enumerate(POSITIVES):
            t0 = time.time()
            r = listen(clips / f"p{i}_{v}.mp3", noisy)
            lat.append(time.time() - t0)
            hit += r["wake"]
            # «pon música» llega a veces como «con música»: es lo que oye Whisper base, con o sin pista
            good = r["wake"] and (SequenceMatcher(None, normalize(r["command"]), normalize(cmd)).ratio() >= 0.8
                                  if cmd else r["command"] == "")
            cmd_ok += bool(good)
            if not good:
                misses.append(f"{text} -> «{r['text']}»")
        for i, text in enumerate(NEGATIVES):
            r = listen(clips / f"n{i}_{v}.mp3", noisy)
            fp += r["wake"]
            fp_old += old_rule(r["text"])
            if r["wake"]:
                misses.append(f"FALSO POSITIVO {text} -> «{r['text']}»")
    total_pos, total_neg = len(VOICES) * len(POSITIVES), len(VOICES) * len(NEGATIVES)
    label = "con ruido (10 dB)" if noisy else "sin ruido"
    check(f"audio {label}: detecta al menos el 85 % de las llamadas", hit >= 0.85 * total_pos,
          f"{hit}/{total_pos}, orden bien separada {cmd_ok}/{total_pos}; " + "; ".join(misses[:4]))
    check(f"audio {label}: ningún falso positivo", fp == 0,
          f"nuevo {fp}/{total_neg} — la regla antigua, con el mismo texto, saltaba {fp_old}/{total_neg}"
          + "".join(f"; {m}" for m in misses if m.startswith("FALSO")))
noise_wakes = sum(client.post("/api/voice/wake/listen", content=pcm16(rng.normal(0, 0.03, 48000).astype(np.float32)),
                              headers=POST).json()["wake"] for _ in range(5))
check("ruido sin voz no la despierta", noise_wakes == 0)
check("responde rápido (media < 1,5 s por tramo en CPU)", np.mean(lat) < 1.5, f"{np.mean(lat) * 1000:.0f} ms de media")

raise SystemExit(summary())
