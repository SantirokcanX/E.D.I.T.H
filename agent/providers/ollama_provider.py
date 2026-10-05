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
        subprocess.Popen(
            [ollama_cmd, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
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

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "deepseek-r1:latest"):
        self.base_url = base_url.rstrip("/")
        self.model = model

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
                    matched = any(self.model in m or m in self.model for m in models)
                    if not matched:
                        available_list = ", ".join(models[:4])
                        return True, f"Ollama activo. Nota: el modelo '{self.model}' no se encontró en la lista local ({available_list}). Se intentará ejecutar o puedes cambiarlo con /model."
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

    def generate_step(
        self,
        messages: List[Dict[str, Any]],
        tools_metadata: List[Dict[str, Any]],
        on_thought_chunk: Optional[Callable[[str], None]] = None,
        on_content_chunk: Optional[Callable[[str], None]] = None
    ) -> AgentStepResponse:
        tools = self._convert_tools_for_ollama(tools_metadata)
        
        # Inyectar instrucción de herramientas en el sistema para reforzar modelos ReAct / DeepSeek-R1
        enhanced_messages = list(messages)
        tools_instructions = (
            "\n\n[HERRAMIENTAS DISPONIBLES]:\n"
            "Tienes acceso a las siguientes herramientas para consultar la web si necesitas información actual o verificar datos:\n"
        )
        for t in tools_metadata:
            tools_instructions += f"- `{t['name']}`: {t['description']}. Parámetros: {json.dumps(t['parameters']['properties'])}\n"
        
        tools_instructions += (
            "\nSi necesitas buscar o consultar una web, puedes usar la llamada a función nativa O escribir un bloque JSON:\n"
            "```json\n"
            '{"action": "web_search", "arguments": {"query": "ejemplo de busqueda"}}\n'
            "```\n"
            "Si ya tienes suficiente información o es una pregunta general, responde directamente al usuario de forma clara y detallada.\n"
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

        payload = {
            "model": self.model,
            "messages": clean_messages,
            "tools": tools,
            "stream": True,
            "options": {
                "temperature": 0.6
            }
        }

        thought_accumulated = ""
        content_accumulated = ""
        tool_calls: List[ToolCall] = []

        in_think_tag = False

        with httpx.Client(timeout=180.0) as client:
            response_ctx = None
            try:
                response_ctx = client.stream("POST", f"{self.base_url}/api/chat", json=payload)
                response = response_ctx.__enter__()
            except (httpx.ConnectError, httpx.NetworkError):
                if response_ctx:
                    try:
                        response_ctx.__exit__(None, None, None)
                    except Exception:
                        pass
                # Intentar auto-iniciar Ollama
                if ensure_ollama_running(self.base_url, timeout=7.0):
                    try:
                        response_ctx = client.stream("POST", f"{self.base_url}/api/chat", json=payload)
                        response = response_ctx.__enter__()
                    except Exception:
                        raise RuntimeError(
                            "Ollama se está iniciando pero aún no está listo para procesar solicitudes. "
                            "Por favor espera unos 5 segundos y vuelve a enviar tu mensaje."
                        )
                else:
                    raise RuntimeError(
                        f"No se pudo conectar a Ollama en {self.base_url}. "
                        "El servicio local no está activo. Abre la aplicación Ollama en tu laptop o ejecuta 'ollama serve' en tu terminal."
                    )

            try:
                if response.status_code != 200:
                    error_body = response.read().decode("utf-8", errors="replace")
                    raise RuntimeError(f"Error de Ollama ({response.status_code}): {error_body}")

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
