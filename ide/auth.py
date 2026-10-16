"""Fase 14: control de acceso a la interfaz web, la API REST y el WebSocket del chat.

* Token de acceso: EDITH_API_TOKEN o data/channels/api_token dentro de la carpeta de datos
  (%LOCALAPPDATA%\\EDITH; se genera solo la primera vez).
* La interfaz lo lleva en una cookie HttpOnly (JavaScript no puede leerla). La recibe:
    - sola, al abrir EDITH desde la propia máquina (127.0.0.1 / localhost, sin proxy delante), o
    - con el enlace /?token=... desde otro dispositivo (python main.py --access-link lo muestra).
* Scripts y herramientas: cabecera "Authorization: Bearer <token>".
* Host permitido en todas las peticiones (bloquea DNS rebinding) y Origin del mismo sitio en el
  WebSocket y en las peticiones que cambian estado (bloquea CSRF desde otras webs).
* Las rutas que ya tienen su propia autenticación siguen igual: bridge de WhatsApp
  (X-Edith-Bridge-Secret), webhooks de Twilio (firma) y /ws/voice (token de un solo uso).
"""

import hmac
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlsplit

from starlette.datastructures import Headers
from starlette.requests import cookie_parser
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

from agent.channels.security import get_api_token
from agent.config import Config

# Rutas con autenticación propia: no usan el token de la interfaz
OWN_AUTH_PATHS = {
    "/api/channels/whatsapp/allowlist", "/api/channels/whatsapp/inbound",  # clave del bridge
    "/api/voice/incoming", "/api/voice/gather", "/api/voice/result", "/api/voice/alarm-ack",  # firma de Twilio
    "/ws/voice",  # token de un solo uso emitido en el webhook firmado
}
# Lo único que se sirve sin token: el icono de la página de acceso
PUBLIC_PATHS = {"/favicon.ico", "/logo.png"}
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
# Si llegan, la petición pasó por un túnel o proxy: no es un navegador de esta misma máquina
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "x-real-ip", "cf-connecting-ip", "true-client-ip")
SAFE_METHODS = {"GET", "HEAD"}
COOKIE_MAX_AGE = 30 * 24 * 3600

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDITH · acceso protegido</title><link rel="icon" href="/logo.png">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0f;color:#ece9f5;
font-family:-apple-system,'Segoe UI',sans-serif}}main{{max-width:460px;padding:28px;border:1px solid #2a2a38;
border-radius:14px;background:#17171f}}h1{{font-size:20px;margin:0 0 10px}}p{{color:#a6a2bd;line-height:1.5}}
code{{background:#20202b;padding:2px 6px;border-radius:6px;color:#ece9f5}}</style></head>
<body><main><h1>🔒 EDITH está protegida</h1><p>{message}</p>
<p>En la máquina donde corre EDITH, ejecuta <code>python main.py --access-link</code> y abre aquí el enlace que muestra.
Desde esa misma máquina basta con abrir <code>http://localhost:8000</code>.</p></main></body></html>"""


def hostname(netloc: str) -> str:
    """'LocalHost:8000' -> 'localhost'; '[::1]:8000' -> '::1'."""
    netloc = (netloc or "").strip().lower()
    if netloc.startswith("["):
        return netloc[1:netloc.find("]")] if "]" in netloc else ""
    return netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc


def extra_hosts() -> set:
    """Hosts configurados además de los locales: el de PUBLIC_BASE_URL y EDITH_ALLOWED_HOSTS."""
    hosts = set(Config.EDITH_ALLOWED_HOSTS)
    if Config.PUBLIC_BASE_URL:
        hosts.add((urlsplit(Config.PUBLIC_BASE_URL).hostname or "").lower())
    hosts.discard("")
    return hosts


def allowed_hosts() -> set:
    return LOOPBACK_HOSTS | extra_hosts()


def origin_allowed(origin: str, host_header: str) -> bool:
    """Origin del mismo sitio que la petición (mismo host y puerto) o de un host configurado."""
    try:
        parts = urlsplit(origin or "")
        name = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False  # incluye "null" (iframes aislados, archivos locales)
    if parts.netloc.lower() == (host_header or "").strip().lower():
        return True
    # Detrás de un túnel el Host puede reescribirse; el host público configurado sigue valiendo.
    # Otro puerto de localhost (otra web local) NO vale.
    return name in extra_hosts()


def token_matches(provided: Optional[str]) -> bool:
    return bool(provided) and hmac.compare_digest(provided.encode("utf-8"), get_api_token().encode("utf-8"))


def cookie_name(scope) -> str:
    """Un nombre por puerto: dos EDITH en la misma máquina no se pisan la cookie."""
    server = scope.get("server") or ("", None)
    return f"edith_token_{server[1]}" if server[1] else "edith_token"


def _request_token(headers: Headers, name: str) -> Tuple[Optional[str], str]:
    auth = headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip(), "bearer"
    value = cookie_parser(headers.get("cookie", "")).get(name)
    return (value, "cookie") if value else (None, "")


def _is_local_browser(scope, headers: Headers) -> bool:
    ip = (scope.get("client") or ("", 0))[0] or ""
    if not (ip == "::1" or ip.startswith("127.")):
        return False
    if hostname(headers.get("host", "")) not in LOOPBACK_HOSTS:
        return False
    return not any(h in headers for h in PROXY_HEADERS)


def _cookie_header(scope, token: str) -> str:
    parts = [f"{cookie_name(scope)}={token}", "Path=/", f"Max-Age={COOKIE_MAX_AGE}", "HttpOnly", "SameSite=Lax"]
    if scope.get("scheme") == "https":
        parts.append("Secure")
    return "; ".join(parts)


def _origin_of(headers: Headers) -> Optional[str]:
    """Origin, o el origen del Referer si el navegador no envió Origin."""
    if "origin" in headers:
        return headers["origin"]
    referer = headers.get("referer")
    if referer:
        parts = urlsplit(referer)
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}"
    return None


class AccessGuard:
    """Middleware ASGI (HTTP y WebSocket) que exige el token salvo en las rutas con autenticación propia."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        path = scope.get("path", "")
        host = headers.get("host", "")
        is_ws = scope["type"] == "websocket"

        if hostname(host) not in allowed_hosts():
            return await self._reject(scope, receive, send, 400,
                                      f"Host no permitido ({hostname(host) or 'vacío'}). "
                                      "Añádelo a EDITH_ALLOWED_HOSTS en .env si es tuyo.")
        if path in OWN_AUTH_PATHS:
            return await self.app(scope, receive, send)

        token, via = _request_token(headers, cookie_name(scope))
        authed = token_matches(token)

        if is_ws:
            origin = headers.get("origin")
            if origin is not None and not origin_allowed(origin, host):
                return await self._reject(scope, receive, send, 403, "Origin no permitido")
            if not authed:
                return await self._reject(scope, receive, send, 401, "Falta el token de acceso")
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET").upper()
        is_page = not path.startswith("/api/")

        if is_page and method in SAFE_METHODS:
            link = parse_qs(scope.get("query_string", b"").decode("latin-1")).get("token")
            if link is not None:
                return await self._login_link(scope, receive, send, path, link[0])
            if authed:
                return await self.app(scope, receive, self._setting_cookie(scope, send, token) if via == "cookie" else send)
            if Config.EDITH_LOCAL_AUTOLOGIN and _is_local_browser(scope, headers):
                return await self.app(scope, receive, self._setting_cookie(scope, send, get_api_token()))
            if path in PUBLIC_PATHS:
                return await self.app(scope, receive, send)

        if not authed:
            return await self._reject(scope, receive, send, 401,
                                      "Falta el token de acceso o no es válido." if not is_page else
                                      "Para entrar desde aquí necesitas el enlace de acceso.")

        if method not in SAFE_METHODS:
            origin = _origin_of(headers)
            if origin is not None:
                if not origin_allowed(origin, host):
                    return await self._reject(scope, receive, send, 403, "Origin no permitido")
            elif via != "bearer":
                # Los navegadores siempre envían Origin en un POST: sin él, solo con Authorization
                return await self._reject(scope, receive, send, 403, "Falta la cabecera Origin")
        return await self.app(scope, receive, send)

    async def _login_link(self, scope, receive, send, path: str, link_token: str):
        if not token_matches(link_token):
            return await self._reject(scope, receive, send, 401, "El enlace de acceso no es válido o caducó.")
        # Cookie y redirección a la misma ruta SIN el token (no queda en la barra ni en el Referer)
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        query.pop("token", None)
        target = path + (f"?{urlencode(query, doseq=True)}" if query else "")
        resp = RedirectResponse(target, status_code=303,
                                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        resp.headers.append("set-cookie", _cookie_header(scope, link_token))
        await resp(scope, receive, send)

    @staticmethod
    def _setting_cookie(scope, send, token: str):
        cookie = _cookie_header(scope, token).encode("latin-1")

        async def wrapped(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"set-cookie", cookie)]}
            await send(message)
        return wrapped

    @staticmethod
    async def _reject(scope, receive, send, status: int, message: str):
        if scope["type"] == "websocket":
            # Cerrar antes de aceptar = el servidor responde 403 al handshake
            await send({"type": "websocket.close", "code": 1008, "reason": message[:120]})
            return
        path = scope.get("path", "")
        if status == 400:
            resp = PlainTextResponse(message, status_code=400)
        elif path.startswith("/api/") or scope.get("method", "GET").upper() not in SAFE_METHODS:
            resp = JSONResponse({"detail": message}, status_code=status)
        else:
            resp = HTMLResponse(LOGIN_PAGE.format(message=message), status_code=status)
        resp.headers["Cache-Control"] = "no-store"
        await resp(scope, receive, send)


def access_links(port: int = 8000) -> list:
    """Enlaces de acceso (con token) para abrir EDITH desde otro dispositivo."""
    token = get_api_token()
    links = [f"http://localhost:{port}/?token={token}"]
    if Config.PUBLIC_BASE_URL:
        links.append(f"{Config.PUBLIC_BASE_URL}/?token={token}")
    links += [f"http://{h}:{port}/?token={token}" for h in Config.EDITH_ALLOWED_HOSTS]
    return links
