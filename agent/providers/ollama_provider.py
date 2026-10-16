"""Ollama provider with real-time reasoning extraction and tool calling."""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import httpx

from .base import BaseLLMProvider, AgentStepResponse, ToolCall


def ensure_ollama_running(base_url: str = "http://localhost:11434", timeout: float = 6.0) -> bool:
    """Verifica si Ollama está respondiendo y, si no, intenta iniciarlo automáticamente en segundo plano."""
    clean_url = base_url.rstrip("/")
    try:
        with httpx.Client(timeout=1.5) as client:
            res = client.get(f"{clean_url}/api/tags")
            if res.status_code == 200:
                return True
    except Exception:
        pass

    # Buscar ejecutable de Ollama
    ollama_cmd = shutil.which("ollama")
    if not ollama_cmd:
        local_app = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if local_app.exists():
            ollama_cmd = str(local_app)

    if not ollama_cmd:
        return False

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    try:
        # Flash attention + caché KV en 8 bits: el contexto ocupa ~la mitad de VRAM,
        # así cabe más del modelo en la GPU (solo aplica cuando EDITH arranca Ollama)
        env = {**os.environ}
        env.setdefault("OLLAMA_FLASH_ATTENTION", "1")
        env.setdefault("OLLAMA_KV_CACHE_TYPE", "q8_0")
        subprocess.Popen(
            [ollama_cmd, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            env=env
        )
    except Exception:
        return False

    # Esperar hasta que responda
    start_time = time.time()
    while time.time() - start_time < timeout:
        time.sleep(0.8)
        try:
            with httpx.Client(timeout=1.5) as client:
                res = client.get(f"{clean_url}/api/tags")
                if res.status_code == 200:
                    return True
        except Exception:
            continue

    return False


class OllamaProvider(BaseLLMProvider):
    """Proveedor para modelos locales a través de Ollama (ej. DeepSeek-R1, Llama 3)."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen3:4b-instruct",
                 keep_alive: Optional[str] = None, num_ctx: Optional[int] = None,
                 think: Optional[bool] = None, deep_model: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        # Modelo que razona para los mensajes difíciles (p. ej. qwen3:4b "Thinking").
        # Las variantes "Thinking" ignoran think=false y mezclan su razonamiento en la
        # respuesta, por eso lo rápido va a `model` (instruct) y lo profundo a `deep_model`.
        self.deep_model = deep_model if deep_model and deep_model != model else None
        self.keep_alive = keep_alive or "30m"
        self.num_ctx = num_ctx
        # Valor por defecto cuando el agente no pide explícitamente razonar o no
        self.think = False if think is None else think
        # Cliente HTTP persistente: reutiliza la conexión TCP en cada paso del razonamiento
        self._client = httpx.Client(timeout=httpx.Timeout(180.0, connect=5.0))
        # Se desactivan solos si el modelo los rechaza (p. ej. un modelo sin soporte de tools)
        self._no_tools: set = set()   # modelos que rechazaron `tools`
        self._no_think: set = set()   # modelos que rechazaron `think`

    def _options(self) -> Dict[str, Any]:
        options: Dict[str, Any] = {"temperature": 0.6}
        if self.num_ctx:
            options["num_ctx"] = self.num_ctx
        return options

    def _model_for(self, think: bool) -> str:
        return self.deep_model if (think and self.deep_model) else self.model

    def warmup(self) -> bool:
        """Carga los modelos en memoria por adelantado para que el primer mensaje responda rápido."""
        try:
            if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
                ensure_ollama_running(self.base_url, timeout=8.0)
            ok = True
            # El de razonamiento primero y el rápido al final: así queda cargado el que más se usa
            # (y el otro ya está en la caché de disco del sistema, lo que acelera el cambio).
            for model in filter(None, [self.deep_model, self.model]):
                # Mismas opciones que el chat: si num_ctx difiere, Ollama recarga el modelo (~10 s)
                res = self._client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model, "prompt": "", "keep_alive": self.keep_alive,
                          "options": self._options()},
                    timeout=120.0,
                )
                ok = ok and res.status_code == 200
            return ok
        except Exception:
            return False

    def is_available(self) -> tuple[bool, str]:
        # Si es local, verificar o intentar auto-iniciar
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            ensure_ollama_running(self.base_url, timeout=4.0)

        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name", "") for m in data.get("models", [])]
                    if not models:
                        return False, "Ollama está corriendo, pero no hay ningún modelo descargado. Ejecuta por ejemplo: `ollama run deepseek-r1:latest`"
                    
                    # Verificar si el modelo configurado o alguna variante está presente
                    wanted = list(filter(None, [self.model, self.deep_model]))
                    missing = [w for w in wanted if not any(w == m or f"{w}:latest" == m for m in models)]
                    if missing:
                        available_list = ", ".join(models[:4])
                        return True, (f"Ollama activo. Nota: no encontré {', '.join(missing)} en la lista local "
                                      f"({available_list}). Descárgalo con `ollama pull {missing[0]}` o cámbialo con /model.")
                    if self.deep_model:
                        return True, f"Ollama activo: '{self.model}' (rápido) + '{self.deep_model}' (razonamiento)."
                    return True, f"Ollama activo con modelo '{self.model}'."
                return False, f"Ollama respondió con código de estado HTTP {res.status_code}."
        except Exception:
            return False, f"No se pudo conectar a Ollama en {self.base_url}. Asegúrate de abrir la app Ollama o ejecutar 'ollama serve'."

    def _convert_tools_for_ollama(self, tools_metadata: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ollama_tools = []
        for tool in tools_metadata:
            ollama_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"]
                }
            })
        return ollama_tools

    @staticmethod
    def _trim_history(payload: Dict[str, Any]) -> bool:
        """Deja solo los mensajes de sistema iniciales y el turno actual (desde el último
        mensaje del usuario). Devuelve False si ya no hay nada que recortar."""
        msgs = payload.get("messages", [])
        last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=None)
        if last_user is None:
            return False
        head = [m for m in msgs[:last_user] if m.get("role") == "system"]
        trimmed = head + msgs[last_user:]
        if len(trimmed) >= len(msgs):
            return False
        payload["messages"] = trimmed
        return True

    def _open_stream(self, payload: Dict[str, Any]):
        """Abre el stream de /api/chat. Si el modelo no soporta `tools` o `think`,
        reintenta sin esa opción y lo recuerda para no volver a pagar el error."""
        for _ in range(3):
            ctx = self._client.stream("POST", f"{self.base_url}/api/chat", json=payload)
            response = ctx.__enter__()
            if response.status_code == 400:
                body = response.read().decode("utf-8", errors="replace").lower()
                ctx.__exit__(None, None, None)
                if "tools" in payload and "tool" in body:
                    self._no_tools.add(payload["model"])
                    payload.pop("tools", None)
                    continue
                if "think" in payload and "think" in body:
                    self._no_think.add(payload["model"])
                    payload.pop("think", None)
                    continue
                if "exceed" in body and "context" in body and self._trim_history(payload):
                    continue  # conversación demasiado larga: reintentar con solo el turno actual
                if "exceed" in body and "context" in body:
                    raise RuntimeError(
                        "El mensaje no cabe en la memoria de trabajo del modelo (OLLAMA_NUM_CTX). "
                        "Prueba con un texto más corto o sube OLLAMA_NUM_CTX en .env.")
                raise RuntimeError(f"Error de Ollama (400): {body}")
            if response.status_code != 200:
                body = response.read().decode("utf-8", errors="replace")
                ctx.__exit__(None, None, None)
                raise RuntimeError(f"Error de Ollama ({response.status_code}): {body}")
            return ctx, response
        raise RuntimeError("Ollama rechazó la solicitud repetidamente.")

    def generate_step(
        self,
        messages: List[Dict[str, Any]],
        tools_metadata: List[Dict[str, Any]],
        on_thought_chunk: Optional[Callable[[str], None]] = None,
        on_content_chunk: Optional[Callable[[str], None]] = None,
        think: Optional[bool] = None
    ) -> AgentStepResponse:
        tools = self._convert_tools_for_ollama(tools_metadata)
        
        # Instrucción breve de herramientas: los esquemas completos ya viajan en `tools`
        # (repetirlos en el prompt solo añadía miles de tokens a procesar en cada paso).
        enhanced_messages = list(messages)
        tools_instructions = ""
        if tools_metadata:
            names = ", ".join(f"`{t['name']}`" for t in tools_metadata)
            tools_instructions = (
                f"\n\n[HERRAMIENTAS DISPONIBLES]: {names}.\n"
                "Úsalas con llamada a función nativa o con un bloque "
                '```json {"action": "<herramienta>", "arguments": {...}}```. '
                "Si no necesitas ninguna, responde directamente.\n"
            )

        # Si el primer mensaje es system, le añadimos las herramientas. Si no, lo agregamos.
        if enhanced_messages and enhanced_messages[0]["role"] == "system":
            enhanced_messages[0] = {
                "role": "system",
                "content": enhanced_messages[0]["content"] + tools_instructions
            }
        else:
            enhanced_messages.insert(0, {
                "role": "system",
                "content": "Eres un agente asistente experto en razonamiento, investigación y análisis." + tools_instructions
            })

        # Sanitizar mensajes para asegurar que todo sea JSON serializable
        clean_messages = []
        for m in enhanced_messages:
            msg_dict = {
                "role": m.get("role", "user"),
                "content": str(m.get("content", ""))
            }
            if "tool_calls" in m and m["tool_calls"]:
                tc_list = []
                for tc in m["tool_calls"]:
                    name = tc.name if hasattr(tc, "name") else (tc.get("name") or (tc.get("function", {}).get("name") if isinstance(tc, dict) else ""))
                    args = tc.arguments if hasattr(tc, "arguments") else (tc.get("arguments") or (tc.get("function", {}).get("arguments") if isinstance(tc, dict) else {}))
                    if name:
                        tc_list.append({
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": args if isinstance(args, dict) else {}
                            }
                        })
                if tc_list:
                    msg_dict["tool_calls"] = tc_list
            clean_messages.append(msg_dict)

        use_think = self.think if think is None else think
        payload = {
            "model": self._model_for(use_think),
            "messages": clean_messages,
            "stream": True,
            "keep_alive": self.keep_alive,
            "options": self._options()
        }
        if tools and payload["model"] not in self._no_tools:
            payload["tools"] = tools
        # Razonamiento por mensaje: en modelos híbridos (qwen3) no hay que recargar nada
        if payload["model"] not in self._no_think:
            payload["think"] = use_think

        thought_accumulated = ""
        content_accumulated = ""
        tool_calls: List[ToolCall] = []

        in_think_tag = False

        response_ctx = None
        try:
            response_ctx, response = self._open_stream(payload)
        except (httpx.ConnectError, httpx.NetworkError):
            # Intentar auto-iniciar Ollama
            if ensure_ollama_running(self.base_url, timeout=7.0):
                try:
                    response_ctx, response = self._open_stream(payload)
                except Exception:
                    raise RuntimeError(
                        "Ollama se está iniciando pero aún no está listo para procesar solicitudes. "
                        "Por favor espera unos 5 segundos y vuelve a enviar tu mensaje."
                    )
            else:
                raise RuntimeError(
                    f"No se pudo conectar a Ollama en {self.base_url}. "
                    "El servicio local no está activo. Abre la aplicación Ollama en tu laptop o ejecuta 'ollama serve'."
                )

        try:
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    chunk_json = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = chunk_json.get("message", {})
                
                # 1. Campo de 'thinking' nativo en Ollama 0.5+
                if "thinking" in msg and msg["thinking"]:
                    t_chunk = msg["thinking"]
                    thought_accumulated += t_chunk
                    if on_thought_chunk:
                        on_thought_chunk(t_chunk)

                # 2. Llamadas a herramientas nativas devueltas por Ollama
                if "tool_calls" in msg and msg["tool_calls"]:
                    for tc in msg["tool_calls"]:
                        func = tc.get("function", {})
                        name = func.get("name", "")
                        args = func.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                pass
                        if name:
                            tool_calls.append(ToolCall(name=name, arguments=args))

                # 3. Contenido de texto y análisis de etiquetas <think> de DeepSeek-R1
                delta = msg.get("content", "")
                if delta:
                    # Procesar etiquetas <think> y </think> si vienen en el contenido
                    if "<think>" in delta:
                        in_think_tag = True
                        parts = delta.split("<think>", 1)
                        # Lo que estuviera antes va al contenido
                        if parts[0]:
                            content_accumulated += parts[0]
                            if on_content_chunk:
                                on_content_chunk(parts[0])
                        delta = parts[1]

                    if in_think_tag:
                        if "</think>" in delta:
                            in_think_tag = False
                            t_part, rest = delta.split("</think>", 1)
                            thought_accumulated += t_part
                            if on_thought_chunk:
                                on_thought_chunk(t_part)
                            if rest:
                                content_accumulated += rest
                                if on_content_chunk:
                                    on_content_chunk(rest)
                        else:
                            thought_accumulated += delta
                            if on_thought_chunk:
                                on_thought_chunk(delta)
                    else:
                        content_accumulated += delta
                        if on_content_chunk:
                            on_content_chunk(delta)
        finally:
            if response_ctx:
                try:
                    response_ctx.__exit__(None, None, None)
                except Exception:
                    pass

        # Si el modelo no usó tool_calls nativos, buscar si produjo un bloque JSON de acción
        if not tool_calls:
            # Buscar patrones ```json { "action": "...", "arguments": ... } ```
            json_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content_accumulated, re.DOTALL)
            for block in json_blocks:
                try:
                    data = json.loads(block)
                    if "action" in data and ("arguments" in data or "query" in data):
                        act_name = data.get("action")
                        args = data.get("arguments", {})
                        if not args and "query" in data:
                            args = {"query": data["query"]}
                        tool_calls.append(ToolCall(name=act_name, arguments=args))
                        # Limpiar el bloque JSON del contenido final
                        content_accumulated = content_accumulated.replace(f"```json\n{block}\n```", "")
                        content_accumulated = content_accumulated.replace(f"```{block}```", "")
                except json.JSONDecodeError:
                    pass

        return AgentStepResponse(
            thought=thought_accumulated.strip(),
            content=content_accumulated.strip(),
            tool_calls=tool_calls
        )
