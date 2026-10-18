"""Pruebas del aviso de versión nueva (Fase 15.5) y del script del instalador (Fase 15.4).
GitHub está simulado. La instalación real se prueba aparte con el EDITH-Setup.exe construido
(ver "Registro de Cambios de EDITH").
Uso:  python tests/test_actualizaciones.py   (desde la raíz del proyecto, con el .venv activado)
"""
import os

os.environ["ML_ENABLED"] = "false"
from entorno import ROOT, Config, FakeProvider, check, sec, summary  # noqa: E402

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import ide.server as srv  # noqa: E402
from agent import updates  # noqa: E402
from agent.paths import VERSION  # noqa: E402
from agent.setup import settings  # noqa: E402

srv.provider = FakeProvider()
AUTH = {"Authorization": f"Bearer {sec.get_api_token()}"}
cli = TestClient(srv.app, base_url="http://127.0.0.1:8000")

# ======================= 1. Comparar versiones =======================
pv = updates.parse_version
check("compara versiones como números (0.1.10 > 0.1.9)", pv("v0.1.10") > pv("0.1.9") > pv("0.0.10") > pv("0.0.9"))
check("acepta la «v» y textos raros", pv("v1.2.3") == (1, 2, 3) and pv("EDITH 0.2") == (0, 2) and pv("") == (0,))

# ======================= 2. Consultar GitHub (simulado) =======================
calls = []
reply = {"status": 404, "json": {}}


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)


def fake_get(url, **kw):
    calls.append((url, kw.get("headers", {})))
    if reply.get("raise"):
        raise httpx.ConnectError("sin internet")
    return FakeResp(reply["status"], reply["json"])


updates.httpx.get = fake_get
Config.UPDATE_CHECK = True
Config.UPDATE_REPO = "SantirokcanX/E.D.I.T.H"

s = updates.check(force=True)
check("sin releases publicados (404): no hay aviso", s.get("latest") is None and not s.get("newer"), s)
check("consulta el último release del repositorio, con User-Agent de EDITH",
      calls[-1][0] == "https://api.github.com/repos/SantirokcanX/E.D.I.T.H/releases/latest"
      and calls[-1][1].get("User-Agent") == f"EDITH/{VERSION}")

reply.update(status=200, json={"tag_name": "v9.0.0", "html_url": "https://github.com/x/releases/tag/v9.0.0",
                               "body": "Novedades", "assets": [{"name": "otra-cosa.zip", "browser_download_url": "https://x/zip"},
                                                               {"name": "EDITH-Setup-9.0.0.exe", "browser_download_url": "https://x/setup.exe"}]})
s = updates.check(force=True)
check("versión más nueva -> aviso con el enlace al instalador", s["newer"] and s["latest"] == "9.0.0"
      and s["setup_url"] == "https://x/setup.exe" and s["current"] == VERSION, s)
n = len(calls)
updates.check()
check("no vuelve a preguntar antes de 24 h", len(calls) == n)
reply.update(json={"tag_name": "v0.0.1", "assets": []})
s = updates.check(force=True)
check("una versión más vieja no avisa", s["latest"] == "0.0.1" and not s["newer"])
reply.update(json={"tag_name": "v9.0.0", "assets": [], "html_url": "https://x/rel"})
updates.check(force=True)
reply["raise"] = True
s = updates.check(force=True)
check("sin internet: no falla y conserva lo último que sabía", s.get("error") == "ConnectError" and s["latest"] == "9.0.0" and s["newer"])
reply["raise"] = False
check("sin instalador en el release, el aviso lleva a la página del release", s.get("url") == "https://x/rel" and not s.get("setup_url"))

Config.UPDATE_CHECK = False
n = len(calls)
s = updates.check(force=True)
check("con el aviso apagado en Ajustes no consulta nada", len(calls) == n and s["enabled"] is False)
Config.UPDATE_CHECK = True
check("desde el código no se consulta en segundo plano (se actualiza con git)", updates.start_background_check(0) is None)

r = cli.get("/api/update", headers=AUTH).json()
check("la interfaz lee el estado en /api/update", r["latest"] == "9.0.0" and r["newer"] and r["current"] == VERSION, r)
n = len(calls)
cli.get("/api/update?check=1", headers=AUTH)
check("/api/update?check=1 consulta en el momento", len(calls) == n + 1)
check("sin token no", cli.get("/api/update").status_code == 401)
check("Ajustes › Avanzado ofrece apagar el aviso", "UPDATE_CHECK" in settings.FIELDS
      and any(f["key"] == "UPDATE_CHECK" for s in settings.SCHEMA if s["id"] == "avanzado" for f in s["fields"]))
setup_js = (ROOT / "ide" / "static" / "setup.js").read_text(encoding="utf-8")
check("el aviso se muestra una vez por versión («Ahora no» lo guarda)", "showUpdateNotice" in setup_js
      and "edith.update.dismissed" in setup_js)

# ======================= 3. Abrir la versión nueva reemplaza a la vieja (0.1.1) =======================
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(ROOT / "desktop"))
import desktop_app  # noqa: E402

vt = desktop_app._version_tuple
check("una EDITH sin instance.json (anterior a la 0.1.1) cuenta como más vieja", vt("") < vt(VERSION))
check("0.0.9 abierta y abres la 0.1.1 -> se reemplaza; misma versión -> no", vt("0.0.9") < vt("0.1.1") and not vt(VERSION) < vt(VERSION))
desktop_app.INSTANCE_FILE.unlink(missing_ok=True)
check("sin archivo, la versión abierta es desconocida", desktop_app.running_instance_version() == "")
desktop_app.write_instance_file()
check("la instancia abierta deja su pid y versión", desktop_app.running_instance_version() == VERSION)
desktop_app.remove_instance_file()
check("y lo borra al cerrar", not desktop_app.INSTANCE_FILE.exists())
rec = __import__("logging").LogRecord("pywebview", 40, "", 0, "WebView2 initialization failed with exception", None, None)
check("un fallo real de WebView2 sí se anota", desktop_app._SkipAbortedWebView().filter(rec))
desktop_app._closing.set()
check("pero si EDITH se está cerrando mientras la ventana arranca, no (es el propio cierre)",
      not desktop_app._SkipAbortedWebView().filter(rec))
desktop_app._closing.clear()

# ======================= 4. Script del instalador (Inno Setup) =======================
iss = (ROOT / "build" / "installer" / "edith.iss").read_text(encoding="utf-8")
check("instalación por usuario, sin administrador", "PrivilegesRequired=lowest" in iss and "DefaultDirName={userpf}\\EDITH" in iss)
check("WhatsApp es un componente opcional", 'Name: "whatsapp"' in iss and "Components: whatsapp" in iss)
check("tareas: acceso directo, iniciar con Windows y Ollama (solo si falta)",
      'Name: "desktopicon"' in iss and 'Name: "startup"' in iss and 'Name: "ollama"' in iss and "Check: not OllamaInstalled" in iss)
check("Ollama se baja del sitio oficial y su instalador se ve", "https://ollama.com/download/OllamaSetup.exe" in iss
      and "SW_SHOW" in iss)
check("«Iniciar con Windows» escribe lo mismo que Ajustes (--tray)", 'ValueData: """{app}\\EDITH.exe"" --tray"' in iss)
check("al desinstalar pregunta si borrar tus datos, con «No» por defecto", "MB_DEFBUTTON2" in iss and "DelTree(Data" in iss)
check("una desinstalación silenciosa nunca borra tus datos", "(not UninstallSilent) and DirExists(Data)" in iss)
check("cierra EDITH con su evento antes de instalar o desinstalar", "Local\\EDITH_Desktop_Quit" in iss
      and "PrepareToInstall" in iss and "InitializeUninstall" in iss)
check("para pruebas se puede no cerrar la EDITH abierta (/NOCLOSEEDITH=1)", "{param:NOCLOSEEDITH|0}" in iss)
check("al actualizar se reemplaza _internal entero", '[InstallDelete]' in iss and '{app}\\_internal' in iss)
check("el acceso del menú Inicio va en su carpeta (no pisa el de la EDITH del código; /NOICONS lo omite)",
      'Name: "{group}\\EDITH"' in iss and "{userprograms}" not in iss and "AllowNoIcons=yes" in iss)
check("una instalación de prueba deja una marca para que el desinstalador tampoco cierre la EDITH abierta",
      ".no-cerrar-edith" in iss and "[UninstallDelete]" in iss)
ps1 = (ROOT / "build" / "build_setup.ps1").read_text(encoding="utf-8-sig")
check("build_setup.ps1 compila el instalador (paso 5) con la versión de VERSION",
      "5/5 EDITH-Setup.exe con Inno Setup" in ps1 and '"/DAppVersion=$Version"' in ps1 and "NoInstaller" in ps1)

raise SystemExit(summary())
