"""Pruebas de archivos adjuntos de cualquier formato (0.1.2): lector universal, subida en el chat,
consulta con adjuntos y WhatsApp. Los archivos se generan aquí; la visión y Whisper están simulados.
Uso:  python tests/test_archivos.py   (desde la raíz del proyecto, con el .venv activado)
"""
import asyncio
import base64
import io
import json
import math
import os
import struct
import wave
import zipfile
from email.message import EmailMessage

os.environ["ML_ENABLED"] = "false"
from entorno import TMP, Config, FakeProvider, check, sec, summary  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
import ide.files_api as files_api  # noqa: E402
import ide.server as srv  # noqa: E402
from agent import files as fr  # noqa: E402
from agent import vision  # noqa: E402
from agent.channels import voice_notes, whatsapp  # noqa: E402
from agent.paths import WORKSPACE_DIR  # noqa: E402
from agent.providers.base import AgentStepResponse, ToolCall  # noqa: E402
from agent.tools.workspace_tools import read_workspace_file  # noqa: E402

# ---------------------------------------------------------------- simulados: visión y Whisper
vision.describe_image = lambda data, q="", mime="": ("Un gráfico de barras con ventas de 2026; dice «Total 4,200».", "local:qwen3-vl:4b")


class Seg:
    def __init__(self, text):
        self.text = text


class FakeWhisper:
    seconds = []

    def transcribe(self, samples, **kw):
        FakeWhisper.seconds.append(round(samples.size / 16000, 1))
        return [Seg("Hola, esta es la grabación de la junta.")], None


voice_notes._whisper = lambda: FakeWhisper()


# ---------------------------------------------------------------- archivos de prueba
def make_pdf(text):
    stream = f"BT /F1 14 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
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


def make_zip(entries, mimetype=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if mimetype:
            z.writestr("mimetype", mimetype)
        for name, content in entries.items():
            z.writestr(name, content)
    return buf.getvalue()


def make_xlsx():
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Ventas"
    ws.append(["Mes", "Total"])
    ws.append(["Enero", 1200])
    ws.append(["Febrero", 3000])
    wb.create_sheet("Gastos").append(["Renta", 8000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_wav(seconds=2.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


def make_mp4(seconds=1.0):
    import av
    import numpy as np
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as out:
        v = out.add_stream("mpeg4", rate=10)
        v.width, v.height, v.pix_fmt = 64, 48, "yuv420p"
        a = out.add_stream("aac", rate=16000)
        a.layout = "mono"
        for i in range(int(seconds * 10)):
            frame = av.VideoFrame.from_ndarray(np.zeros((48, 64, 3), dtype=np.uint8), format="rgb24")
            for p in v.encode(frame):
                out.mux(p)
        samples = (np.sin(np.arange(int(16000 * seconds)) * 2 * np.pi * 440 / 16000) * 0.3).astype(np.float32)
        for start in range(0, samples.size, 1024):
            af = av.AudioFrame.from_ndarray(samples[start:start + 1024].reshape(1, -1), format="flt", layout="mono")
            af.sample_rate = 16000
            for p in a.encode(af):
                out.mux(p)
        for p in list(v.encode()) + list(a.encode()):
            out.mux(p)
    return buf.getvalue()


def make_eml():
    m = EmailMessage()
    m["From"] = "Banco <avisos@banco.mx>"
    m["To"] = "diego@ejemplo.mx"
    m["Subject"] = "Tu estado de cuenta"
    m.set_content("Tu saldo es de 15,300 pesos.")
    m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="estado.pdf")
    return m.as_bytes()


SAMPLES = {
    "notas.txt": ("Hola ñandú, reunión el martes.").encode("utf-8"),
    "viejo.txt": "Canción de año nuevo".encode("cp1252"),
    "unicode.txt": "\ufeffTexto en UTF-16 con acentos: árbol".encode("utf-16"),
    "ventas.csv": b"mes,total\nenero,1200\nfebrero,3000\n",
    "datos.json": json.dumps({"cliente": "ACME", "monto": 999}).encode(),
    "pagina.html": b"<html><head><style>p{}</style><script>alert(1)</script></head><body><h1>Precios</h1><p>Laptop $15,999</p></body></html>",
    "script.py": b"def suma(a, b):\n    return a + b\n",
    "factura.pdf": make_pdf("Factura 2026 Total a pagar 1500 pesos"),
    "contrato.docx": make_zip({"word/document.xml": '<?xml version="1.0"?><w:document xmlns:w="x"><w:body><w:p><w:r><w:t>Contrato de renta</w:t></w:r></w:p><w:p><w:r><w:t>Monto 8,000</w:t></w:r></w:p></w:body></w:document>'}),
    "cuentas.xlsx": make_xlsx(),
    "presentacion.pptx": make_zip({"ppt/presentation.xml": "<p/>",
                                   "ppt/slides/slide1.xml": "<p:sld><a:t>Plan 2027</a:t><a:t>Crecer 20%</a:t></p:sld>",
                                   "ppt/slides/slide2.xml": "<p:sld><a:t>Gracias</a:t></p:sld>"}),
    "carta.odt": make_zip({"content.xml": "<office:document-content><text:p>Querido Diego</text:p><text:p>Saludos</text:p></office:document-content>"},
                          mimetype="application/vnd.oasis.opendocument.text"),
    "libro.epub": make_zip({"OEBPS/cap1.xhtml": "<html><body><h1>Capítulo 1</h1><p>Érase una vez</p></body></html>"},
                           mimetype="application/epub+zip"),
    "nota.rtf": rb"{\rtf1\ansi{\fonttbl\f0 Arial;}\f0 Hola Mundo, a\'f1o nuevo\par Segunda l\'ednea}",
    "correo.eml": make_eml(),
    "grafica.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
    "junta.wav": make_wav(2.0),
    "paquete.zip": make_zip({"leeme.txt": "Instrucciones del paquete", "datos/tabla.csv": "a,b\n1,2\n", "setup.exe": "MZ\x90\x00binario"}),
    "instalador.exe": b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 100,
    "raro.bin": bytes(range(256)) * 4,
    "viejo.xls": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100,
}
try:
    SAMPLES["video.mp4"] = make_mp4(1.0)
except Exception as e:  # sin códec en este equipo: se informa y se sigue
    print(f"(sin vídeo de prueba: {e})")

# ======================= 1. Lector universal =======================
R = {name: fr.read_any(data, name, "", "¿qué dice?") for name, data in SAMPLES.items()}


def has(name, *needles, kind=None):
    r = R[name]
    ok = "error" not in r and all(n in r.get("text", "") + r.get("note", "") + r.get("label", "") for n in needles)
    return ok and (kind is None or r.get("kind") == kind)


check("texto UTF-8 con ñ", has("notas.txt", "ñandú", kind="texto"))
check("texto viejo de Windows (cp1252) sin caracteres rotos", has("viejo.txt", "Canción de año nuevo"))
check("texto UTF-16", has("unicode.txt", "árbol"))
check("CSV y JSON", has("ventas.csv", "febrero,3000", "CSV") and has("datos.json", '"monto": 999', "JSON"))
check("HTML: texto sin etiquetas ni scripts", has("pagina.html", "Precios", "Laptop $15,999") and "alert" not in R["pagina.html"]["text"])
check("código fuente", has("script.py", "def suma", "código py"))
check("PDF con número de páginas", has("factura.pdf", "Total a pagar 1500", "PDF de 1 páginas", kind="pdf"))
check("Word (.docx)", has("contrato.docx", "Contrato de renta", "Monto 8,000", kind="word"))
check("Excel con varias hojas", has("cuentas.xlsx", "Hoja «Ventas»", "Febrero\t3000", "Hoja «Gastos»", "Renta\t8000", kind="hoja"))
check("PowerPoint por diapositiva", has("presentacion.pptx", "[Diapositiva 1]", "Plan 2027", "[Diapositiva 2]", kind="presentacion"))
check("OpenDocument (.odt)", has("carta.odt", "Querido Diego", "Saludos", kind="word"))
check("EPUB", has("libro.epub", "Capítulo 1", "Érase una vez", kind="libro"))
check("RTF con acentos", has("nota.rtf", "Hola Mundo, año nuevo", "Segunda línea"), R["nota.rtf"].get("text"))
check("correo .eml con remitente, asunto, cuerpo y adjuntos",
      has("correo.eml", "De: Banco", "Asunto: Tu estado de cuenta", "15,300 pesos", "Adjuntos: estado.pdf", kind="correo"))
check("imagen: la describe la visión (con su texto)", has("grafica.png", "gráfico de barras", "Total 4,200", kind="imagen"))
check("audio: lo transcribe Whisper", has("junta.wav", "grabación de la junta", kind="audio") and 2.0 in FakeWhisper.seconds,
      FakeWhisper.seconds)
if "video.mp4" in R:
    check("vídeo: transcribe su pista de audio y dice su tamaño", has("video.mp4", "grabación de la junta", "vídeo 64×48", kind="video"),
          R["video.mp4"].get("label"))
check("ZIP: lista lo que trae y lee lo de dentro", has("paquete.zip", "Contiene 3 archivos", "leeme.txt", "Instrucciones del paquete",
                                                      "tabla.csv", kind="comprimido"))
check("un programa dentro del ZIP no se ejecuta ni se lee", "binario" not in R["paquete.zip"]["text"].split("setup.exe")[-1][:200]
      or "MZ" not in R["paquete.zip"]["text"])
check("programas (.exe): se identifican y NUNCA se ejecutan", R["instalador.exe"]["kind"] == "programa"
      and "no lo ejecuto" in R["instalador.exe"]["note"] and R["instalador.exe"]["text"] == "")
check("binario desconocido: dice qué es y su huella", R["raro.bin"]["kind"] == "binario" and "SHA-256" in R["raro.bin"]["note"])
check("Excel antiguo (.xls): explica cómo convertirlo", ".xlsx" in R["viejo.xls"]["note"])
r = fr.read_any(SAMPLES["factura.pdf"], "factura.txt")
check("manda el contenido, no la extensión (un PDF llamado .txt se lee como PDF)", r.get("kind") == "pdf")
check("un ZIP dañado da un error claro", "dañado" in fr.read_any(b"PK\x03\x04roto", "x.zip").get("error", ""))
big = fr.read_any(("x" * 70000).encode(), "grande.txt")
check("textos enormes se recortan y lo indica", big["truncated"] and len(big["text"]) == fr.MAX_TEXT)
blocks = fr.describe_for_model([dict(R["cuentas.xlsx"], saved="adjuntos/c.xlsx", text_file="adjuntos/c.xlsx.txt"),
                                dict(big, saved="adjuntos/g.txt", text_file="adjuntos/g.txt.txt")], budget=6000)
check("varios archivos se reparten el espacio del modelo y dicen dónde está el texto completo",
      len(blocks) == 2 and "read_workspace_file" in blocks[1] and len("".join(blocks)) < 9000)

# ======================= 2. Subir archivos (/api/files/upload) =======================
fake = FakeProvider()
srv.provider = fake
srv.edith_agent.provider = fake
srv.ml_engine = None
srv.voice_engine.enabled = False
TOKEN = sec.get_api_token()
BASE = "http://127.0.0.1:8000"
POST = {"Authorization": f"Bearer {TOKEN}", "Origin": BASE}
cli = TestClient(srv.app, base_url=BASE)

r = cli.post("/api/files/upload", headers=POST, files=[
    ("files", ("factura.pdf", SAMPLES["factura.pdf"], "application/pdf")),
    ("files", ("../../.env", b"MALICIOSO=1", "text/plain")),
    ("files", ("cuentas.xlsx", SAMPLES["cuentas.xlsx"], "application/octet-stream"))])
up = r.json().get("files", [])
check("sube varios archivos a workspace/adjuntos", r.status_code == 200 and len(up) == 3
      and all(f["id"].startswith("adjuntos/") for f in up), r.text[:200])
check("un nombre con ../ no sale de la carpeta", up[1]["id"].count("/") == 1 and (WORKSPACE_DIR / up[1]["id"]).resolve().parent
      == files_api.ATTACH_DIR.resolve() and not (WORKSPACE_DIR.parent / ".env").exists())
check("sin token no se sube nada", cli.post("/api/files/upload", files=[("files", ("a.txt", b"x"))], headers={"Origin": BASE}).status_code == 401)
check("otra web no puede subir archivos", cli.post("/api/files/upload", files=[("files", ("a.txt", b"x"))],
                                                   headers={**POST, "Origin": "http://sitio-ajeno.example"}).status_code == 403)
check("máximo 10 archivos por mensaje", cli.post("/api/files/upload", headers=POST,
                                                 files=[("files", (f"{i}.txt", b"x")) for i in range(11)]).status_code == 400)
files_api.MAX_BYTES = 100
r = cli.post("/api/files/upload", headers=POST, files=[("files", ("grande.bin", b"x" * 500))])
check("archivos de más de 50 MB se rechazan (y no quedan a medias)", r.status_code == 413
      and not list(files_api.ATTACH_DIR.glob("*grande.bin")))
files_api.MAX_BYTES = 50 * 1024 * 1024

# ======================= 3. Consulta con adjuntos =======================
seen = []


class Recorder(FakeProvider):
    def generate_step(self, messages, tools_metadata, on_thought_chunk=None, on_content_chunk=None, think=None):
        last = messages[-1]
        if last["role"] == "user":
            seen.append(last["content"])
            if "guárdalo" in last["content"]:
                return AgentStepResponse(tool_calls=[ToolCall("save_to_workspace", {"filename": "resumen.md", "content": "x"})])
        return AgentStepResponse(content="Listo, lo revisé.")


rec = Recorder()
srv.provider = rec
srv.edith_agent.provider = rec
WS = "ws://127.0.0.1:8000/ws/chat"


def ask(prompt, ids, confirm_answer=None):
    msgs = []
    with cli.websocket_connect(WS, headers=POST) as ws:
        ws.send_json({"action": "query", "prompt": prompt, "attachments": ids, "mode": "standard", "reasoning": "fast", "speak": False})
        while True:
            m = ws.receive_json()
            msgs.append(m)
            if m.get("type") == "confirm_request":
                ws.send_json({"action": "confirm", "id": m["id"], "approved": bool(confirm_answer)})
            if m.get("type") == "final_answer":
                return msgs


ids = [up[0]["id"], up[2]["id"]]
msgs = ask("¿cuánto debo en total?", ids)
p = seen[-1]
check("el modelo recibe el contenido de los adjuntos y tu pregunta", "Total a pagar 1500" in p and "Febrero\t3000" in p
      and p.endswith("¿cuánto debo en total?"), p[-200:])
check("cada adjunto va marcado como dato no confiable", p.count("DATO NO CONFIABLE") == 2)
check("mientras lee, la interfaz dice qué archivo está leyendo",
      any(m.get("type") == "status" and "Leyendo «factura.pdf»" in m.get("text", "") for m in msgs))
hist = [m for m in srv.edith_agent.conversation_history if m["role"] == "user"][-1]["content"]
check("al historial va solo la lista de adjuntos (no llena el contexto de los siguientes mensajes)",
      "[Adjuntos:" in hist and "Total a pagar 1500" not in hist and "workspace/adjuntos/" in hist, hist[-200:])
session = json.dumps(srv.memory_manager.load_session(srv.memory_manager.current_session_id), ensure_ascii=False)
check("la conversación guardada en disco tampoco lleva el contenido", "Total a pagar 1500" not in session and "[Adjuntos:" in session)
txt = [f for f in files_api.ATTACH_DIR.glob("*factura.pdf.txt")]
check("el texto completo queda en workspace/adjuntos para consultarlo después", txt and "Total a pagar 1500" in txt[0].read_text(encoding="utf-8"))

msgs = ask("", [up[0]["id"]])
check("solo adjuntos, sin texto: EDITH los revisa y dice qué contienen", seen[-1].endswith("dime qué contienen."))
msgs = ask("haz un resumen y guárdalo", [up[0]["id"]], confirm_answer=False)
check("con adjuntos en el turno, guardar archivos pide tu permiso (podrían traer órdenes ocultas)",
      any(m.get("type") == "confirm_request" and m.get("tool") == "save_to_workspace" for m in msgs))
msgs = ask("lee esto", ["adjuntos/../../../.env", "C:/Windows/win.ini"])
check("ids que no son adjuntos subidos se rechazan", sum(1 for m in msgs if m.get("type") == "error" and "No encontré" in m.get("message", "")) == 2)

srv.provider = fake
srv.edith_agent.provider = fake
long = WORKSPACE_DIR / "largo.txt"
long.write_text("a" * 30000, encoding="utf-8")
part1 = read_workspace_file("largo.txt")
part3 = read_workspace_file("largo.txt", offset=24000)
check("read_workspace_file: 12 000 caracteres por lectura y dice cómo seguir",
      part1.split("\n")[0] == "a" * 12000 and "offset=12000" in part1 and part3 == "a" * 6000)

# ======================= 4. WhatsApp: cualquier archivo =======================
Config.WHATSAPP_ENABLED = True
Config.AUTHORIZED_PHONE_NUMBERS = ["525533334444"]
seen.clear()


def wa(payload):
    return asyncio.run(whatsapp.handle_inbound(rec, {"from": "525533334444", **payload}))


r = wa({"document_b64": base64.b64encode(SAMPLES["cuentas.xlsx"]).decode(), "document_name": "cuentas.xlsx"})
check("Excel por WhatsApp: lo lee y lo resume", seen and "Renta\t8000" in seen[-1] and "resúmelo" in seen[-1])
if "video.mp4" in SAMPLES:
    r = wa({"document_b64": base64.b64encode(SAMPLES["video.mp4"]).decode(), "document_name": "video.mp4", "document_mime": "video/mp4"})
    check("vídeo por WhatsApp: transcribe lo que se dice", "grabación de la junta" in seen[-1])
n = len(seen)
r = wa({"document_b64": base64.b64encode(SAMPLES["instalador.exe"]).decode(), "document_name": "instalador.exe"})
check("un programa por WhatsApp: dice qué es, no lo ejecuta y no hace trabajar al modelo",
      "no lo ejecuto" in r.get("reply_text", "") and len(seen) == n, r.get("reply_text"))
check("el bridge acepta vídeos y archivos de cualquier tipo (25 MB)",
      "msg?.videoMessage" in (whatsapp.__file__ and open(os.path.join(os.path.dirname(srv.__file__), "..", "bridges", "whatsapp", "bridge.mjs"), encoding="utf-8").read())
      and whatsapp.MAX_MEDIA_BYTES == 25 * 1024 * 1024)

raise SystemExit(summary())
