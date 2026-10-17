"""Pruebas de la Fase 12 (navegador propio de EDITH con Playwright y Microsoft Edge).
Usa Edge SIN ventana contra una tienda de prueba local: nada aparece en pantalla ni sale a internet.
Uso:  python tests/test_navegador.py   (desde la raíz del proyecto, con el .venv activado)
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

os.environ["ML_ENABLED"] = "false"
from entorno import TMP, Config, FakeProvider, check, summary  # noqa: E402

from agent import tools as tools_pkg  # noqa: E402
from agent.core import safety  # noqa: E402
from agent.core.reasoning_agent import AgentCallbacks, ReasoningAgent  # noqa: E402
from agent.providers.base import AgentStepResponse, ToolCall  # noqa: E402
from agent.tools import browser_tools as bt  # noqa: E402

PDF = b"%PDF-1.4\n% lista de precios de prueba\n"
HOME = """<!doctype html><html><head><title>Tienda de prueba</title></head><body>
<h1>Bienvenido a la tienda</h1><p>Precios bajos todo el año.</p>
<a href="/ofertas">Ofertas</a> <a href="javascript:void(0)">Menú</a> <a href="/precios.pdf">Lista de precios</a>
<form action="/buscar" method="get">
  <label for="q">Buscar productos</label><input id="q" name="q">
  <label for="pw">Contraseña</label><input id="pw" name="pw" type="password">
  <input name="tarjeta" placeholder="Número de tarjeta">
  <button type="submit">Buscar</button>
</form>
<input type="hidden" name="secreto" value="x"><div style="display:none"><a href="/oculto">oculto</a></div>
</body></html>"""


class Shop(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(HOME)
        elif u.path == "/ofertas":
            self._send("<title>Ofertas</title><p>Ofertas de la semana: Laptop $15,999</p><a href='/'>Inicio</a>")
        elif u.path == "/buscar":
            q = parse_qs(u.query).get("q", [""])[0]
            self._send(f"<title>Resultados</title><p>Resultados para: {q}</p>")
        elif u.path == "/precios.pdf":
            self._send(PDF, "application/pdf", {"Content-Disposition": 'attachment; filename="precios.pdf"'})
        else:
            self.send_response(404)
            self.end_headers()


srv = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


def find(snapshot, label):
    for line in snapshot.get("elements", "").splitlines():
        if f"«{label}»" in line:
            return int(line.split("]")[0].strip("["))
    return None


def names(agent=None):
    meta = agent.tools_metadata if agent else tools_pkg.available_tools_metadata()
    return {t["name"] for t in meta if t["name"].startswith("browser_")}


check("sin página abierta el modelo solo ve browser_open (ahorra contexto)", names() == {"browser_open"}, names())
check("perfil propio en la carpeta de datos de EDITH (no tu Edge)", str(TMP) in str(bt.PROFILE_DIR))

s = bt.browser_open(BASE)
check("abre la página con Edge sin ventana", s.get("title") == "Tienda de prueba" and "Precios bajos" in s.get("text", ""),
      s.get("error") or s.get("title"))
check("con página abierta aparecen las demás herramientas", names() >= {"browser_click", "browser_fill", "browser_follow_link"})
els = s.get("elements", "")
check("lista numerada de enlaces, campos y botones", "enlace «Ofertas»" in els and "campo «Buscar productos»" in els
      and "botón «Buscar»" in els, els)
check("un enlace javascript: cuenta como botón (no se «sigue» sin permiso)", "botón «Menú»" in els)
check("no lista elementos ocultos", "oculto" not in els)
check("marca contraseña y tarjeta como sensibles", "«Contraseña» (sensible" in els and "tarjeta» (sensible" in els.lower(), els)

r = bt.browser_follow_link(find(s, "Buscar"))
check("browser_follow_link no pulsa botones", "no es un enlace" in r.get("error", ""))
r = bt.browser_follow_link(find(s, "Ofertas"))
check("sigue un enlace", "Laptop $15,999" in r.get("text", ""), r.get("error"))
s = bt.browser_open(BASE)

check("escribe en un campo normal", bt.browser_fill(find(s, "Buscar productos"), "laptop").get("status") == "escrito")
r = bt.browser_fill(find(s, "Contraseña"), "secreta123")
check("nunca escribe contraseñas", "no lo escribo yo" in r.get("error", ""), r)
r = bt.browser_fill(find(s, "Número de tarjeta"), "4111111111111111")
check("nunca escribe datos de tarjeta", "no lo escribo yo" in r.get("error", ""), r)
r = bt.browser_click(find(s, "Buscar"))
check("pulsa el botón y envía el formulario", "Resultados para: laptop" in r.get("text", ""), r.get("error") or r.get("text"))
check("un número que no existe da un error claro", "No hay ningún elemento" in bt.browser_fill(999, "x").get("error", ""))

s = bt.browser_open(BASE)
r = bt.browser_download(element_id=find(s, "Lista de precios"))
dest = bt.DOWNLOADS_DIR / "precios.pdf"
check("descarga un PDF pulsando su enlace (al workspace/descargas)", r.get("status") == "descargado" and dest.read_bytes() == PDF, r)
r = bt.browser_download(url=BASE + "/precios.pdf")
check("descarga desde una URL directa sin pisar el anterior", r.get("file") == "descargas/precios (2).pdf", r)
check("no abre file:// ni javascript:", "http" in bt.browser_open("file:///C:/Windows/win.ini").get("error", "")
      and "http" in bt.browser_open("javascript:alert(1)").get("error", ""))

check("pulsar botones y descargar piden permiso siempre",
      {"browser_click", "browser_download"} <= safety.CONFIRM_ALWAYS and "browser_fill" not in safety.CONFIRM_ALWAYS)
g = safety.TurnGuard()
g.record("browser_open")
check("lo que se lee de la web es dato no confiable (luego guardar archivos pide permiso)",
      g.external and g.confirmation_reason("save_to_workspace") is not None)
g = safety.TurnGuard()
g.record("obsidian_read_note")
check("tras leer tus notas, abrir o escribir en la web pide permiso (no se lleva datos)",
      g.confirmation_reason("browser_open") and g.confirmation_reason("browser_fill"))
check("mostrar la ventana solo desde la laptop", "browser_show" in tools_pkg.LOCAL_ONLY_TOOLS)


class ShopPlan(FakeProvider):
    def generate_step(self, messages, tools_metadata, on_thought_chunk=None, on_content_chunk=None, think=None):
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return AgentStepResponse(tool_calls=[ToolCall("browser_open", {"url": BASE})])
        if len(tool_msgs) == 1:
            sid = find({"elements": str(tool_msgs[0]["content"]).split("elements")[-1].replace("\\n", "\n")}, "Buscar")
            return AgentStepResponse(tool_calls=[ToolCall("browser_click", {"element_id": sid or 6})])
        return AgentStepResponse(content="Listo: " + str(tool_msgs[-1]["content"])[:60])


asked = []
agent = ReasoningAgent(provider=ShopPlan(), max_iterations=4)
res = agent.run("busca en la tienda", AgentCallbacks(on_confirm=lambda t, a, r: asked.append((t, safety.describe_action(t, a))) or False))
check("el agente pide permiso antes de pulsar, mostrando qué botón y en qué página",
      asked and asked[0][0] == "browser_click" and "«Buscar»" in asked[0][1][1] and BASE in asked[0][1][1], asked[:1])
check("si no autorizas, no pulsa", "no autorizó" in res.answer.lower() or "NO autorizó" in res.answer, res.answer[:100])

check("cerrar el navegador vuelve a ocultar sus herramientas", bt.browser_close().get("status") == "cerrado"
      and names() == {"browser_open"})
bt._worker.shutdown()
srv.shutdown()
raise SystemExit(summary())
