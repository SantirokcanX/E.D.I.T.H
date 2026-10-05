"""Google Gemini provider with native reasoning and function calling."""

import os
from typing import List, Dict, Any, Optional, Callable
from .base import BaseLLMProvider, AgentStepResponse, ToolCall

try:
    from google import genai
    from google.genai import types
    from google.genai.errors import APIError
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False


class GeminiProvider(BaseLLMProvider):
    """Proveedor para Google Gemini (Gemini 2.5 Flash / Gemini 2.0 con soporte de razonamiento y herramientas)."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.5-flash"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model
        self.client = None
        if self.api_key and GENAI_AVAILABLE:
            self.client = genai.Client(api_key=self.api_key)

    def is_available(self) -> tuple[bool, str]:
        if not GENAI_AVAILABLE:
            return False, "El paquete 'google-genai' no está instalado en el entorno."
        if not self.api_key:
            return False, (
                "No se ha configurado la variable GEMINI_API_KEY. "
                "Agrega tu clave en el archivo .env o usa Ollama para ejecución local gratuita."
            )
        try:
            # Prueba ligera de verificación
            client = genai.Client(api_key=self.api_key)
            return True, f"Google Gemini configurado y listo con modelo '{self.model}'."
        except Exception as e:
            return False, f"Error al inicializar cliente de Google Gemini: {str(e)}"

    def _build_tools_config(self, tools_metadata: List[Dict[str, Any]]) -> List[types.Tool]:
        declarations = []
        for t in tools_metadata:
            # Formatear parámetros a tipos de OpenAPI/Gemini
            properties = {}
            for param_name, param_info in t["parameters"].get("properties", {}).items():
                p_type = param_info.get("type", "STRING").upper()
                if p_type == "STRING":
                    dtype = types.Type.STRING
                elif p_type == "INTEGER":
                    dtype = types.Type.INTEGER
                elif p_type == "NUMBER":
                    dtype = types.Type.NUMBER
                elif p_type == "BOOLEAN":
                    dtype = types.Type.BOOLEAN
                else:
                    dtype = types.Type.STRING

                properties[param_name] = types.Schema(
                    type=dtype,
                    description=param_info.get("description", "")
                )

            decl = types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties=properties,
                    required=t["parameters"].get("required", [])
                )
            )
            declarations.append(decl)
            
        return [types.Tool(function_declarations=declarations)]

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> tuple[Optional[str], List[types.Content]]:
        system_instruction = None
        gemini_contents = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if role == "system":
                system_instruction = content
            elif role == "user":
                gemini_contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=str(content))]
                    )
                )
            elif role == "assistant":
                parts = []
                if content:
                    parts.append(types.Part.from_text(text=str(content)))
                # Si el asistente llamó a una herramienta anteriormente
                if "tool_calls" in msg and msg["tool_calls"]:
                    for tc in msg["tool_calls"]:
                        name = tc.name if hasattr(tc, "name") else (tc.get("name") if isinstance(tc, dict) else "")
                        args = tc.arguments if hasattr(tc, "arguments") else (tc.get("arguments") if isinstance(tc, dict) else {})
                        if name:
                            parts.append(
                                types.Part.from_function_call(
                                    name=name,
                                    args=args or {}
                                )
                            )
                if parts:
                    gemini_contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                # Respuesta de una herramienta ejecutada
                tool_name = msg.get("name", "tool")
                tool_result = msg.get("content", {})
                if not isinstance(tool_result, dict):
                    tool_result = {"output": str(tool_result)}
                gemini_contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=tool_name,
                                response=tool_result
                            )
                        ]
                    )
                )

        return system_instruction, gemini_contents

    def generate_step(
        self,
        messages: List[Dict[str, Any]],
        tools_metadata: List[Dict[str, Any]],
        on_thought_chunk: Optional[Callable[[str], None]] = None,
        on_content_chunk: Optional[Callable[[str], None]] = None
    ) -> AgentStepResponse:
        if not self.client:
            self.client = genai.Client(api_key=self.api_key)

        system_instruction, contents = self._convert_messages(messages)
        tools = self._build_tools_config(tools_metadata)

        # Configurar pensamiento (thinking) si está soportado
        thinking_config = None
        try:
            # Activar razonamiento para modelos Gemini 2.5
            thinking_config = types.ThinkingConfig(thinking_budget=-1)
        except Exception:
            pass

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=tools,
            temperature=0.6,
            thinking_config=thinking_config
        )

        thought_accumulated = ""
        content_accumulated = ""
        tool_calls: List[ToolCall] = []

        try:
            response_stream = self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config
            )

            for chunk in response_stream:
                if not chunk.candidates:
                    continue
                candidate = chunk.candidates[0]
                if not candidate.content or not candidate.content.parts:
                    continue

                for part in candidate.content.parts:
                    # Comprobar si la parte es razonamiento (pensamiento)
                    is_thought = getattr(part, "thought", False)
                    if is_thought:
                        thought_chunk = part.text or ""
                        thought_accumulated += thought_chunk
                        if on_thought_chunk and thought_chunk:
                            on_thought_chunk(thought_chunk)
                    elif part.text:
                        text_chunk = part.text
                        content_accumulated += text_chunk
                        if on_content_chunk and text_chunk:
                            on_content_chunk(text_chunk)

                    # Comprobar si pide ejecutar una función/herramienta
                    if part.function_call:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        tool_calls.append(ToolCall(name=fc.name, arguments=args))

        except Exception as e:
            # Fallback sin stream si hubiera problemas con streaming
            if not content_accumulated and not tool_calls:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config
                )
                if response.candidates and response.candidates[0].content:
                    for part in response.candidates[0].content.parts:
                        if getattr(part, "thought", False):
                            thought_accumulated += part.text or ""
                        elif part.text:
                            content_accumulated += part.text
                        if part.function_call:
                            fc = part.function_call
                            tool_calls.append(ToolCall(name=fc.name, arguments=dict(fc.args or {})))
            else:
                raise e

        return AgentStepResponse(
            thought=thought_accumulated.strip(),
            content=content_accumulated.strip(),
            tool_calls=tool_calls
        )
