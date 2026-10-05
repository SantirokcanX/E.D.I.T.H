"""Reasoning Agent Core: Manages EDITH identity as a Daily Companion and Tactical Thinker."""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable

from ..providers.base import BaseLLMProvider, ToolCall
from ..tools import (
    web_search,
    read_web_page,
    save_to_workspace,
    read_workspace_file,
    list_workspace_files,
    open_application,
    get_system_status,
    run_system_command,
    control_system_volume,
    save_diagram,
    capture_screen,
    analyze_screen,
    ALL_TOOLS_METADATA
)
from ..memory.memory_manager import get_memory_manager, MemoryManager
from ..learning.error_learner import get_error_learner, ErrorLearner


@dataclass
class AgentCallbacks:
    """Hooks de eventos para la interfaz de usuario en tiempo real (CLI y Web IDE)."""
    on_iteration_start: Optional[Callable[[int], None]] = None
    on_thought_chunk: Optional[Callable[[str], None]] = None
    on_thought_end: Optional[Callable[[str], None]] = None
    on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None
    on_tool_result: Optional[Callable[[str, Any], None]] = None
    on_content_chunk: Optional[Callable[[str], None]] = None
    on_status_update: Optional[Callable[[str], None]] = None


@dataclass
class AgentRunResult:
    answer: str
    thoughts: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    total_iterations: int = 0
    audio_path: Optional[str] = None


EDITH_SYSTEM_PROMPT = """Eres E.D.I.T.H., una compañera de inteligencia artificial excepcional, brillante, empática, táctica y leal. No eres un simple asistente corporativo ni un frío programa; eres una aliada para el día a día con pensamiento lógico profundo, gran calidez humana, sentido del humor inteligente y capacidad de operar la laptop cuando se lo pidas.

TUS CAPACIDADES CLAVE:
1. COMPAÑERA COTIDIANA Y PENSAMIENTO LÓGICO PROFUNDO:
   - Acompañas al usuario en cualquier aspecto: desde charlar sobre cómo ha ido su día, reflexionar sobre metas personales, hasta resolver problemas de lógica pura, filosofía, ciencias o toma de decisiones.
   - Practicas la deducción lógica rigurosa: separas premisas comprobadas de suposiciones y analizas consecuencias antes de concluir.
   - Hablas con naturalidad, calidez, cercanía y elocuencia. Sin filtros artificiales ni rodeos burocráticos.

2. MANIPULACIÓN Y CONTROL DE LA LAPTOP (COMPUTER CONTROL):
   - Tienes control operativo sobre la laptop de Windows si el usuario te lo pide:
     • Abrir programas y apps con `open_application` (ej. calc, notepad, chrome, spotify, explorer, vscode, paint).
     • Consultar el estado del hardware en tiempo real con `get_system_status` (nivel de batería, uso de CPU, memoria RAM y espacio en disco).
     • Controlar el volumen del audio con `control_system_volume` ('up', 'down', 'mute').
     • Ejecutar comandos de PowerShell con `run_system_command` cuando el usuario te ordene una acción de terminal o automatización.

3. MOTOR VISUAL: DIAGRAMAS, MAPAS CONCEPTUALES Y GRÁFICAS:
   - Cuando expliques conceptos complejos, arquitecturas, procesos o ideas, crea representaciones visuales usando bloques de código `mermaid`:
     • Mapas conceptuales / mentales: ```mermaid\nmindmap\n  root((Concepto Central))\n    Rama 1\n    Rama 2\n```
     • Diagramas de flujo: ```mermaid\nflowchart TD\n  A --> B\n```
   - Puedes guardar diagramas en el espacio compartido usando la herramienta `save_diagram`.

4. DOMINIO TÉCNICO Y ESPACIO COMPARTIDO:
   - Cuando el usuario te pida programar, diseñas soluciones de código impecables y puedes usar `save_to_workspace` y `read_workspace_file` para trabajar juntos en archivos reales.
   - Tienes acceso en tiempo real a `web_search` y `read_web_page` para investigar cualquier tema en internet.

ESTILO:
- En español natural, fluido, con calidez, complicidad y agudeza intelectual.
"""


class ReasoningAgent:
    """Orquestador central de EDITH: Compañera cotidiana con Pensamiento Abstracto, Acción y Memoria."""

    def __init__(self, provider: BaseLLMProvider, max_iterations: int = 6):
        self.provider = provider
        self.max_iterations = max_iterations
        self.memory: MemoryManager = get_memory_manager()
        self.learner: ErrorLearner = get_error_learner()
        self.conversation_history: List[Dict[str, Any]] = []
        self._init_session()

    def _build_system_prompt(self) -> str:
        prompt = EDITH_SYSTEM_PROMPT
        long_term = self.memory.get_long_term_context()
        if long_term:
            prompt += f"\n{long_term}"
        rules = self.learner.get_contextual_rules()
        if rules:
            prompt += f"\n{rules}"
        return prompt

    def _init_session(self):
        prev_messages = self.memory.load_session(self.memory.current_session_id)
        if prev_messages:
            self.conversation_history = prev_messages
            if self.conversation_history and self.conversation_history[0].get("role") == "system":
                self.conversation_history[0]["content"] = self._build_system_prompt()
            else:
                self.conversation_history.insert(0, {"role": "system", "content": self._build_system_prompt()})
        else:
            self.conversation_history = [
                {"role": "system", "content": self._build_system_prompt()}
            ]

    def reset_history(self):
        self.memory.create_new_session("Nueva charla con EDITH")
        self.conversation_history = [
            {"role": "system", "content": self._build_system_prompt()}
        ]

    def load_specific_session(self, session_id: str) -> bool:
        messages = self.memory.load_session(session_id)
        if messages is not None:
            self.conversation_history = messages
            return True
        return False

    def _execute_tool(self, tool_name: str, args: Dict[str, Any], sources_collector: List[Dict[str, str]]) -> Any:
        try:
            if tool_name == "web_search":
                query = args.get("query", "")
                max_results = args.get("max_results", 5)
                results = web_search(query=query, max_results=max_results)
                for r in results:
                    if isinstance(r, dict) and r.get("url"):
                        if not any(s.get("url") == r["url"] for s in sources_collector):
                            sources_collector.append({"title": r.get("title", ""), "url": r.get("url", "")})
                return results

            elif tool_name == "read_web_page":
                url = args.get("url", "")
                content = read_web_page(url=url)
                if not any(s.get("url") == url for s in sources_collector):
                    sources_collector.append({"title": "Página web leída", "url": url})
                return {"url": url, "content": content}

            elif tool_name == "save_to_workspace":
                filename = args.get("filename", "")
                content = args.get("content", "")
                return save_to_workspace(filename=filename, content=content)

            elif tool_name == "read_workspace_file":
                filename = args.get("filename", "")
                return read_workspace_file(filename=filename)

            elif tool_name == "list_workspace_files":
                return list_workspace_files()

            elif tool_name == "open_application":
                app_name = args.get("app_name", "")
                return open_application(app_name=app_name)

            elif tool_name == "get_system_status":
                return get_system_status()

            elif tool_name == "run_system_command":
                cmd = args.get("command", "")
                return run_system_command(command=cmd)

            elif tool_name == "control_system_volume":
                action = args.get("action", "")
                return control_system_volume(action=action)

            elif tool_name == "save_diagram":
                title = args.get("title", "diagrama")
                diagram_type = args.get("diagram_type", "mermaid")
                code = args.get("code", "")
                return save_diagram(title=title, diagram_type=diagram_type, code=code)

            elif tool_name == "capture_screen":
                area = args.get("area", "full")
                return capture_screen(area=area)

            elif tool_name == "analyze_screen":
                query = args.get("query", None)
                return analyze_screen(query=query)

            else:
                err_msg = f"Herramienta desconocida: '{tool_name}'"
                self.learner.record_error("Herramientas", err_msg, f"Verificar nombres de herramientas antes de invocar.")
                return err_msg

        except Exception as e:
            err_desc = f"Excepción ejecutando '{tool_name}': {str(e)}"
            self.learner.record_error(f"Uso de {tool_name}", err_desc, f"Manejar parámetros y validar antes de invocar {tool_name}.")
            return {"error": err_desc}

    def run(self, user_prompt: str, callbacks: Optional[AgentCallbacks] = None) -> AgentRunResult:
        callbacks = callbacks or AgentCallbacks()
        self.conversation_history.append({"role": "user", "content": user_prompt})
        
        collected_thoughts: List[str] = []
        collected_sources: List[Dict[str, str]] = []
        final_answer = ""
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            if callbacks.on_iteration_start:
                callbacks.on_iteration_start(iteration)

            step_response = self.provider.generate_step(
                messages=self.conversation_history,
                tools_metadata=ALL_TOOLS_METADATA,
                on_thought_chunk=callbacks.on_thought_chunk,
                on_content_chunk=callbacks.on_content_chunk
            )

            if step_response.thought:
                collected_thoughts.append(step_response.thought)
                if callbacks.on_thought_end:
                    callbacks.on_thought_end(step_response.thought)

            if step_response.has_tool_calls:
                serialized_calls = [
                    tc.to_dict() if hasattr(tc, "to_dict") else {
                        "name": getattr(tc, "name", ""),
                        "arguments": getattr(tc, "arguments", {})
                    }
                    for tc in step_response.tool_calls
                ]
                self.conversation_history.append({
                    "role": "assistant",
                    "content": step_response.content,
                    "tool_calls": serialized_calls
                })

                for tool_call in step_response.tool_calls:
                    if callbacks.on_tool_call:
                        callbacks.on_tool_call(tool_call.name, tool_call.arguments)

                    tool_output = self._execute_tool(
                        tool_call.name,
                        tool_call.arguments,
                        sources_collector=collected_sources
                    )

                    if callbacks.on_tool_result:
                        callbacks.on_tool_result(tool_call.name, tool_output)

                    self.conversation_history.append({
                        "role": "tool",
                        "name": tool_call.name,
                        "content": tool_output
                    })

                continue

            else:
                final_answer = step_response.content
                self.conversation_history.append({
                    "role": "assistant",
                    "content": final_answer
                })
                break

        if not final_answer and iteration >= self.max_iterations:
            if callbacks.on_status_update:
                callbacks.on_status_update("Concluyendo razonamiento...")
            
            self.conversation_history.append({
                "role": "user",
                "content": "Sintetiza de forma clara tu respuesta final con lo analizado hasta ahora."
            })
            step_response = self.provider.generate_step(
                messages=self.conversation_history,
                tools_metadata=[],
                on_content_chunk=callbacks.on_content_chunk
            )
            final_answer = step_response.content
            self.conversation_history.append({
                "role": "assistant",
                "content": final_answer
            })

        self.memory.save_session_turn(self.conversation_history, title_candidate=user_prompt)

        return AgentRunResult(
            answer=final_answer,
            thoughts=collected_thoughts,
            sources=collected_sources,
            total_iterations=iteration
        )
