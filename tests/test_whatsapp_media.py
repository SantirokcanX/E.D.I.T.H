"""Pruebas de fotos y documentos por WhatsApp (Fase 9), visión local y del razonamiento automático
que aprende de cuándo eliges 🔬 Profundo. Ollama y el bridge están simulados.
Uso:  python tests/test_whatsapp_media.py   (desde la raíz del proyecto, con el .venv activado)
"""
import asyncio
import base64
import io
import json
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

os.environ["ML_ENABLED"] = "false"
from entorno import ROOT, TMP, Config, FakeProvider, check, sec, summary  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
import ide.server as srv  # noqa: E402
from agent import documents, vision  # noqa: E402
from agent.channels import whatsapp  # noqa: E402
from agent.core import reasoning_agent as rag  # noqa: E402
from agent.core.reasoning_agent import AgentCallbacks, ReasoningAgent  # noqa: E402
from agent.ml import deep_router  # noqa: E402
from agent.paths import WORKSPACE_DIR  # noqa: E402
from agent.providers.base import AgentStepResponse, ToolCall  # noqa: E402


def make_pdf(text: str) -> bytes:
    """PDF mínimo con una línea de texto (Helvetica), con su tabla xref correcta."""
    stream = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, o in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(paragraphs) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document '
                   'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                   f"{body}</w:body></w:document>")
    return buf.getvalue()


# ======================= 1. Documentos =======================
pdf = make_pdf("Factura 2026-10 Total a pagar 1500 pesos")
r = documents.extract_text(pdf, "factura.pdf")
check("lee el texto de un PDF", "Total a pagar 1500" in r.get("text", "") and r.get("pages") == 1, r)
r = documents.extract_text(make_docx(["Contrato de renta", "Monto: 8,000 al mes"]), "contrato.docx")
check("lee un Word (.docx) sin librerías extra", "Contrato de renta" in r.get("text", "") and "8,000" in r["text"], r)
check("lee texto plano", documents.extract_text("hola ñ".encode("utf-8"), "nota.txt").get("text") == "hola ñ")
r = documents.extract_text(("x" * 9000).encode(), "largo.txt")
check("recorta documentos largos (no satura al modelo)", r["truncated"] and len(r["text"]) <= documents.MAX_CHARS + 1)
check("un tipo desconocido se explica", "PDF, Word o texto" in documents.extract_text(b"PK", "tabla.xlsx").get("error", ""))
check("un PDF roto no revienta", "error" in documents.extract_text(b"%PDF-1.4 roto", "roto.pdf"))
check("nombres de archivo seguros", documents.safe_filename('..\\..\\malo:"x".pdf') == ".._.._malo__x_.pdf".strip(" .")
      or "\\" not in documents.safe_filename('..\\..\\malo:"x".pdf'))

# ======================= 2. Visión (Ollama simulado) =======================
chat_requests = []
installed = {"vision": False}


class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        data = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        models = [{"name": "qwen3:4b-instruct"}] + ([{"name": "qwen3-vl:4b"}] if installed["vision"] else [])
        self._json({"models": models})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        chat_requests.append(body)
        self._json({"message": {"role": "assistant", "content": "Un gato naranja dormido sobre una mesa de madera."}})


ollama = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
threading.Thread(target=ollama.serve_forever, daemon=True).start()
Config.OLLAMA_BASE_URL = f"http://127.0.0.1:{ollama.server_address[1]}"
Config.VISION_MODEL = "qwen3-vl:4b"
os.environ.pop("GEMINI_API_KEY", None)
IMG = b"\x89PNG\r\n\x1a\nfalso"

desc, who = vision.describe_image(IMG, "¿qué ves?")
check("sin modelo de visión ni Gemini: lo dice y explica cómo activarlo", desc is None and "qwen3-vl:4b" in who, who)
installed["vision"] = True
desc, who = vision.describe_image(IMG, "¿qué animal es?")
check("con el modelo local instalado describe la imagen", desc and "gato naranja" in desc and who == "local:qwen3-vl:4b", (desc, who))
req = chat_requests[-1]
check("la imagen va al modelo local (nada sale de la laptop) y sin razonamiento",
      req["model"] == "qwen3-vl:4b" and req["messages"][0]["images"] == [base64.b64encode(IMG).decode()]
      and req["think"] is False and "¿qué animal es?" in req["messages"][0]["content"])

# ======================= 3. WhatsApp: fotos y documentos =======================
seen_prompts = []


class Recorder(FakeProvider):
    def generate_step(self, messages, tools_metadata, on_thought_chunk=None, on_content_chunk=None, think=None):
        last = messages[-1]
        if last["role"] == "user":
            seen_prompts.append(last["content"])
        return AgentStepResponse(content="Entendido.")


prov = Recorder()
Config.WHATSAPP_ENABLED = True
Config.AUTHORIZED_PHONE_NUMBERS = ["525533334444"]
SENDER = "525533334444"


def inbound(payload):
    return asyncio.run(whatsapp.handle_inbound(prov, {"from": SENDER, **payload}))


r = inbound({"text": "¿qué raza es?", "image_b64": base64.b64encode(IMG).decode(), "image_mime": "image/png"})
p = seen_prompts[-1]
check("foto con pregunta: el modelo recibe lo que se ve y la pregunta", "gato naranja" in p and p.endswith("¿qué raza es?"), p[-120:])
check("lo que trae la foto va marcado como dato no confiable", "DATO NO CONFIABLE" in p and "foto de WhatsApp" in p)
check("y contesta", r.get("reply_text") == "Entendido.")
r = inbound({"image_b64": base64.b64encode(IMG).decode()})
check("foto sin texto: pregunta por defecto «dime qué ves»", "dime qué ves" in seen_prompts[-1])
installed["vision"] = False
n = len(seen_prompts)
r = inbound({"image_b64": base64.b64encode(IMG).decode()})
check("sin visión: avisa en vez de inventar", "todavía no puedo verla" in r.get("reply_text", "") and len(seen_prompts) == n)
installed["vision"] = True

r = inbound({"document_b64": base64.b64encode(pdf).decode(), "document_name": "factura.pdf", "document_mime": "application/pdf"})
p = seen_prompts[-1]
check("PDF por WhatsApp: el modelo lee su texto y lo resume", "Total a pagar 1500" in p and "resúmelo" in p, p[-160:])
check("el documento queda en workspace/recibidos", (WORKSPACE_DIR / "recibidos" / "factura.pdf").read_bytes() == pdf)
r = inbound({"text": "¿cuánto pago?", "document_b64": base64.b64encode(make_docx(["Renta: 8,000"])).decode(),
             "document_name": "contrato.docx"})
check("Word con pregunta", "Renta: 8,000" in seen_prompts[-1] and seen_prompts[-1].endswith("¿cuánto pago?"))
r = inbound({"document_b64": base64.b64encode(b"x" * (10 * 1024 * 1024 + 1)).decode(), "document_name": "enorme.pdf"})
check("archivos de más de 10 MB se rechazan", "10 MB" in r.get("reply_text", ""))
r = inbound({"document_b64": base64.b64encode(b"PK").decode(), "document_name": "hoja.xlsx"})
check("tipo no soportado: lo explica", "PDF, Word o texto" in r.get("reply_text", ""))

# ======================= 4. Contenido externo = acciones con permiso =======================
class SavePlan(FakeProvider):
    def generate_step(self, messages, tools_metadata, on_thought_chunk=None, on_content_chunk=None, think=None):
        if messages[-1]["role"] == "user":
            return AgentStepResponse(tool_calls=[ToolCall("save_to_workspace", {"filename": "x.md", "content": "y"})])
        return AgentStepResponse(content="ok")


asked = []
agent = ReasoningAgent(provider=SavePlan(), max_iterations=3)
agent.run("guarda esto", AgentCallbacks(on_confirm=lambda t, a, r: asked.append(t) or True))
check("un mensaje normal no pide permiso para guardar", asked == [])
agent.run("guarda lo que dice el documento", AgentCallbacks(on_confirm=lambda t, a, r: asked.append(t) or True), None, True)
check("con una foto o documento en el mensaje, guardar pide permiso (podría traer órdenes ocultas)", asked == ["save_to_workspace"])

bridge = (ROOT / "bridges" / "whatsapp" / "bridge.mjs").read_text(encoding="utf-8")
check("el bridge descarga fotos y documentos (con límite de 10 MB)",
      "payload.image_b64" in bridge and "payload.document_b64" in bridge and "MAX_MEDIA_BYTES" in bridge)

# ======================= 5. Razonamiento que aprende de 🔬 Profundo =======================
router = deep_router.DeepThinkRouter(path=TMP / "deep_router.joblib")
TEXT = "planea mi itinerario de viaje a Japón con presupuesto detallado por día"
check("recién creado no decide nada (la heurística manda)", not router.wants_deep(TEXT, 0.75) and router.updates == 0)
for i in range(6):
    router.learn(f"planea mi itinerario de viaje a {['Japón', 'Perú', 'Italia', 'Chile', 'Corea', 'España'][i]} "
                 "con presupuesto detallado por día", True)
    router.learn(["hola", "gracias", "qué hora es", "pon música", "abre spotify", "buenas noches"][i], False)
check("tras tus elecciones, aprende que esos planes los quieres a fondo", router.wants_deep(TEXT, 0.75), router.prob_deep(TEXT))
check("y lo casual sigue rápido", not router.wants_deep("hola, cómo estás", 0.75))
check("se guarda en disco", (TMP / "deep_router.joblib").exists()
      and deep_router.DeepThinkRouter(path=TMP / "deep_router.joblib").updates == 12)

deep_router._router = router
Config.ML_ENABLED = True
Config.OLLAMA_THINK_MODE = "auto"
a = ReasoningAgent(provider=FakeProvider(), max_iterations=1)
check("modo automático: usa lo aprendido además de la heurística",
      a.resolve_think(TEXT) is True and a.resolve_think("resuelve 2x+3=7") is True and a.resolve_think("hola") is False)
check("tu elección explícita siempre manda", a.resolve_think(TEXT, think=False) is False)
Config.ML_ENABLED = False
check("con el ML apagado, solo la heurística", a.resolve_think(TEXT) is False)

Config.ML_ENABLED = True
fake = FakeProvider()
srv.provider = fake
srv.edith_agent.provider = fake
srv.ml_engine = None
srv.voice_engine.enabled = False
before = router.updates
token = sec.get_api_token()
local = TestClient(srv.app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50003))
with local.websocket_connect("ws://127.0.0.1:8000/ws/chat",
                             headers={"Authorization": f"Bearer {token}", "Origin": "http://127.0.0.1:8000"}) as ws:
    ws.send_json({"action": "query", "prompt": "organiza mi mudanza con lista de pendientes por semana",
                  "mode": "standard", "reasoning": "deep", "speak": False})
    while ws.receive_json().get("type") != "final_answer":
        pass
check("al pulsar 🔬 Profundo en el chat, EDITH aprende de esa elección", router.updates == before + 1)
Config.ML_ENABLED = False

ollama.shutdown()
raise SystemExit(summary())
