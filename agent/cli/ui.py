"""Rich-based interactive Terminal User Interface for EDITH (Companion & Tactical Thinker)."""

import sys
from typing import Optional, Dict, Any
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table
from rich.live import Live
from rich.text import Text

from ..config import Config
from ..providers import get_provider
from ..core.reasoning_agent import ReasoningAgent, AgentCallbacks
from ..coworking.team import CoworkingTeam, TeamMemberEvent
from ..voice.voice_engine import get_voice_engine, speak_async
from ..memory.memory_manager import get_memory_manager
from ..learning.error_learner import get_error_learner


class AgentCLI:
    """Consola interactiva de EDITH: Compañera de día a día, pensamiento abstracto y código."""

    def __init__(self):
        self.console = Console()
        self.provider_name = Config.PROVIDER
        self.provider = None
        self.agent: Optional[ReasoningAgent] = None
        self.team: Optional[CoworkingTeam] = None
        self.voice = get_voice_engine()
        self.memory = get_memory_manager()
        self.learner = get_error_learner()
        self.coworking_mode = False
        self.init_agent()

    def init_agent(self, provider_name: Optional[str] = None, model: Optional[str] = None):
        if provider_name:
            self.provider_name = provider_name
            
        try:
            self.provider = get_provider(self.provider_name, model=model)
            self.agent = ReasoningAgent(self.provider, max_iterations=Config.MAX_ITERATIONS)
            self.team = CoworkingTeam(self.provider)
        except Exception as e:
            self.console.print(f"[bold red]Error al inicializar proveedor '{self.provider_name}': {str(e)}[/bold red]")

    def print_banner(self):
        model_display = getattr(self.provider, "model", "Desconocido")
        avail, status_msg = self.provider.is_available() if self.provider else (False, "No inicializado")
        
        status_color = "green" if avail else "yellow"
        voice_desc = f"{self.voice.current_voice_info['name']}" if self.voice.enabled else "Silenciada"

        banner_text = Text()
        banner_text.append("👓 E.D.I.T.H. — Tu Compañera Inteligente, Reflexiva & Táctica\n", style="bold cyan")
        banner_text.append("════════════════════════════════════════════════════════════════════════════════════\n", style="dim")
        banner_text.append(f"• Motor / Modelo:     ", style="bold white")
        banner_text.append(f"{self.provider_name.upper()} ({model_display})\n", style="bold magenta")
        banner_text.append(f"• Estado:             ", style="bold white")
        banner_text.append(f"{status_msg}\n", style=status_color)
        banner_text.append(f"• Voz Natural:        ", style="bold white")
        banner_text.append(f"{voice_desc}\n", style="green" if self.voice.enabled else "dim")
        banner_text.append(f"• Modo de trabajo:    ", style="bold white")
        banner_text.append(f"{'👥 Co-Working en Equipo (EDITH + Scout + Auditor)' if self.coworking_mode else '💬 Tú a Tú con EDITH'}\n", style="cyan" if self.coworking_mode else "white")
        banner_text.append(f"• Memoria de sesión:  ", style="bold white")
        banner_text.append(f"{self.memory.current_session_id}\n\n", style="dim yellow")
        banner_text.append("Comandos útiles:\n", style="dim italic")
        banner_text.append("  /voice [on|off|<voz>]     - Alternar o cambiar voz (elvira, dalia, ximena, salome)\n", style="dim")
        banner_text.append("  /coworking [on|off]       - Alternar modo equipo multi-agente\n", style="dim")
        banner_text.append("  /sessions                 - Ver historial de charlas previas\n", style="dim")
        banner_text.append("  /load <id>                - Continuar una charla anterior\n", style="dim")
        banner_text.append("  /new                      - Iniciar conversación en limpio\n", style="dim")
        banner_text.append("  /learnings                - Ver lecciones aprendidas de errores\n", style="dim")
        banner_text.append("  /help                     - Ayuda detallada | /exit para salir", style="dim")

        self.console.print(Panel(banner_text, border_style="cyan", expand=False))

    def run_coworking_query(self, user_query: str):
        self.console.print(Panel(
            "[bold cyan]👥 Iniciando protocolo de Co-Working en Equipo...[/bold cyan]\n"
            "[dim]EDITH (Estratega) ➔ Scout (Investigador Web) ➔ Auditor (Crítico Dialéctico) ➔ EDITH (Síntesis)[/dim]",
            border_style="magenta"
        ))

        def on_team_event(event: TeamMemberEvent):
            border = "cyan"
            icon = "👓"
            if event.member == "Scout":
                border = "yellow"
                icon = "🕵️"
            elif event.member == "Auditor":
                border = "red"
                icon = "🧐"

            self.console.print(Panel(
                Markdown(event.content),
                title=f"{icon} {event.member} — {event.role}",
                border_style=border,
                padding=(0, 1)
            ))

        with self.console.status("[bold magenta]Equipo colaborando...", spinner="aesthetic"):
            try:
                result = self.team.collaborate(user_query, on_event=on_team_event)
            except Exception as e:
                self.console.print(f"[bold red]Error en Co-Working: {str(e)}[/bold red]")
                return

        if self.voice.enabled and result.get("answer"):
            speak_async(result["answer"])

        self.console.print(f"\n[bold green]✓ Entregable guardado en workspace/informe_coworking_reciente.md[/bold green]")

    def run_standard_query(self, user_query: str):
        avail, msg = self.provider.is_available()
        if not avail:
            self.console.print(Panel(
                f"[bold red]Aviso de proveedor:[/bold red] {msg}\n\n"
                "[dim]Puedes cambiar al proveedor Gemini usando `/provider gemini` o activar Ollama con `ollama run deepseek-r1`.[/dim]",
                title="⚠️ Motor no disponible",
                border_style="red"
            ))
            return

        thought_chunks = []
        current_live: Optional[Live] = None

        def on_iteration_start(iteration: int):
            self.console.print(f"\n[dim italic]─── Reflexión paso {iteration} ───[/dim italic]")

        def on_thought_chunk(chunk: str):
            nonlocal current_live
            thought_chunks.append(chunk)
            full_thought = "".join(thought_chunks)
            if not current_live:
                current_live = Live(
                    Panel(
                        Text(full_thought, style="dim italic white"),
                        title="🧠 Pensamiento Abstracto & Primeros Principios (EDITH)",
                        border_style="magenta",
                        expand=False
                    ),
                    console=self.console,
                    refresh_per_second=10
                )
                current_live.start()
            else:
                current_live.update(
                    Panel(
                        Text(full_thought, style="dim italic white"),
                        title="🧠 Pensamiento Abstracto & Primeros Principios (EDITH)",
                        border_style="magenta",
                        expand=False
                    )
                )

        def on_thought_end(full_thought: str):
            nonlocal current_live
            if current_live:
                current_live.stop()
                current_live = None

        def on_tool_call(tool_name: str, args: Dict[str, Any]):
            nonlocal current_live
            if current_live:
                current_live.stop()
                current_live = None

            if tool_name == "web_search":
                q = args.get("query", "")
                self.console.print(Panel(
                    f"[bold cyan]🔍 Buscando en la web:[/bold cyan] [italic]\"{q}\"[/italic]",
                    border_style="cyan",
                    padding=(0, 1)
                ))
            elif tool_name == "read_web_page":
                u = args.get("url", "")
                self.console.print(Panel(
                    f"[bold yellow]📄 Leyendo artículo web:[/bold yellow] [underline]{u}[/underline]",
                    border_style="yellow",
                    padding=(0, 1)
                ))
            elif tool_name == "save_to_workspace":
                f = args.get("filename", "")
                self.console.print(Panel(
                    f"[bold green]💾 Guardando en workspace:[/bold green] [underline]{f}[/underline]",
                    border_style="green",
                    padding=(0, 1)
                ))
            else:
                self.console.print(f"[bold blue]⚙️ Herramienta:[/bold blue] {tool_name} con {args}")

        def on_tool_result(tool_name: str, result: Any):
            if tool_name == "web_search":
                count = len(result) if isinstance(result, list) else 0
                self.console.print(f"  [dim green]✓ Se encontraron {count} fuentes.[/dim green]")
            elif tool_name == "read_web_page":
                length = len(result.get("content", "")) if isinstance(result, dict) else len(str(result))
                self.console.print(f"  [dim green]✓ Información asimilada ({length} caracteres).[/dim green]")
            elif tool_name == "save_to_workspace":
                self.console.print(f"  [dim green]✓ Archivo actualizado en el workspace.[/dim green]")

        callbacks = AgentCallbacks(
            on_iteration_start=on_iteration_start,
            on_thought_chunk=on_thought_chunk,
            on_thought_end=on_thought_end,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result
        )

        with self.console.status("[bold cyan]EDITH pensando...", spinner="dots"):
            try:
                run_result = self.agent.run(user_prompt=user_query, callbacks=callbacks)
            except Exception as e:
                if current_live:
                    current_live.stop()
                self.console.print(f"\n[bold red]Error durante la ejecución:[/bold red] {str(e)}")
                return

        if current_live:
            current_live.stop()

        self.console.print("\n")
        self.console.print(Panel(
            Markdown(run_result.answer if run_result.answer else "_No se generó respuesta._"),
            title="💬 EDITH",
            border_style="cyan",
            padding=(1, 2)
        ))

        if self.voice.enabled and run_result.answer:
            speak_async(run_result.answer)

        if run_result.sources:
            table = Table(title="🌐 Fuentes y referencias consultadas", show_lines=False, border_style="dim cyan")
            table.add_column("Título", style="bold white", overflow="fold")
            table.add_column("Enlace", style="underline cyan")
            for src in run_result.sources:
                title = src.get("title") or "Fuente web"
                table.add_row(title[:60] + ("..." if len(title) > 60 else ""), src.get("url", ""))
            self.console.print(table)

    def run_query(self, user_query: str):
        if self.coworking_mode:
            self.run_coworking_query(user_query)
        else:
            self.run_standard_query(user_query)

    def start_repl(self):
        self.print_banner()

        while True:
            try:
                self.console.print()
                user_input = self.console.input("[bold cyan]Tú > [/bold cyan]").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    cmd_parts = user_input.split(maxsplit=1)
                    cmd = cmd_parts[0].lower()
                    arg = cmd_parts[1].strip() if len(cmd_parts) > 1 else ""

                    if cmd in ("/exit", "/quit", "/salir"):
                        self.console.print("[bold yellow]EDITH: Que tengas un excelente día. Hasta la próxima.[/bold yellow]")
                        break

                    elif cmd in ("/help", "/ayuda"):
                        self.print_help()
                        continue

                    elif cmd == "/voice":
                        if arg.lower() in ("on", "activar", "si", "1"):
                            self.voice.enabled = True
                            self.console.print(f"[green]Voz de EDITH activada ({self.voice.current_voice_info['name']}).[/green]")
                        elif arg.lower() in ("off", "desactivar", "no", "0"):
                            self.voice.enabled = False
                            self.voice.stop_audio()
                            self.console.print("[yellow]Voz silenciada.[/yellow]")
                        elif arg.lower() in self.voice.VOICES:
                            self.voice.set_voice(arg.lower())
                            self.console.print(f"[green]Voz cambiada a: {self.voice.current_voice_info['name']}[/green]")
                        else:
                            self.voice.enabled = not self.voice.enabled
                            self.console.print(f"Voz: { '[green]Activada (' + self.voice.current_voice_info['name'] + ')[/green]' if self.voice.enabled else '[yellow]Silenciada[/yellow]' }")
                            self.console.print("[dim]Voces disponibles: elvira, dalia, ximena, salome[/dim]")
                        continue

                    elif cmd == "/coworking":
                        if arg.lower() in ("on", "activar"):
                            self.coworking_mode = True
                            self.console.print("[bold cyan]Modo Co-Working en equipo ACTIVADO (EDITH + Scout + Auditor).[/bold cyan]")
                        elif arg.lower() in ("off", "desactivar"):
                            self.coworking_mode = False
                            self.console.print("[dim]Modo Co-Working desactivado. Charlando directamente con EDITH.[/dim]")
                        else:
                            self.coworking_mode = not self.coworking_mode
                            self.console.print(f"Co-Working: { '[bold cyan]Activado[/bold cyan]' if self.coworking_mode else '[dim]Desactivado[/dim]' }")
                        continue

                    elif cmd == "/sessions":
                        self.print_sessions()
                        continue

                    elif cmd == "/load":
                        if arg:
                            ok = self.agent.load_specific_session(arg)
                            if ok:
                                self.console.print(f"[bold green]Conversación '{arg}' recuperada con éxito.[/bold green]")
                            else:
                                self.console.print(f"[red]No se encontró la sesión '{arg}'.[/red]")
                        else:
                            self.console.print("[red]Uso: /load <id_de_sesion>[/red]")
                        continue

                    elif cmd == "/new":
                        self.agent.reset_history()
                        self.console.print(f"[bold green]Nueva conversación iniciada: {self.memory.current_session_id}[/bold green]")
                        continue

                    elif cmd == "/learnings":
                        self.print_learnings()
                        continue

                    elif cmd == "/clear":
                        self.agent.reset_history()
                        self.console.print("[green]Historial de charla reiniciado.[/green]")
                        continue

                    elif cmd == "/provider":
                        if arg in ("ollama", "gemini"):
                            self.init_agent(provider_name=arg)
                            self.console.print(f"[bold green]Proveedor cambiado a '{arg}'.[/bold green]")
                        else:
                            self.console.print("[red]Uso: /provider <ollama|gemini>[/red]")
                        continue

                    elif cmd == "/model":
                        if arg:
                            self.init_agent(model=arg)
                            self.console.print(f"[bold green]Modelo cambiado a '{arg}'.[/bold green]")
                        else:
                            self.console.print("[red]Uso: /model <nombre_modelo>[/red]")
                        continue

                    else:
                        self.console.print(f"[red]Comando no reconocido: '{cmd}'. Escribe /help.[/red]")
                        continue

                self.run_query(user_input)

            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[bold yellow]Sesión finalizada por el usuario.[/bold yellow]")
                break
            except Exception as e:
                self.console.print(f"\n[bold red]Error imprevisto:[/bold red] {str(e)}")

    def print_sessions(self):
        sessions = self.memory.list_sessions()
        table = Table(title="Charlas previas con EDITH", border_style="dim cyan")
        table.add_column("ID de Sesión", style="bold cyan")
        table.add_column("Título", style="white")
        table.add_column("Mensajes", style="yellow")
        table.add_column("Última actualización", style="dim")
        for s in sessions[:10]:
            table.add_row(s["id"], s["title"], str(s["messages_count"]), s["updated_at"][:19])
        self.console.print(table)

    def print_learnings(self):
        table = Table(title="🌱 Evolución y Aprendizaje Continuo de EDITH", border_style="magenta")
        table.add_column("Contexto", style="bold yellow")
        table.add_column("Fallo anterior", style="red")
        table.add_column("Regla / Aprendizaje", style="green")
        for l in self.learner.learnings:
            table.add_row(l.get("task", ""), l.get("error", "")[:45] + "...", l.get("lesson", ""))
        self.console.print(table)

    def print_help(self):
        table = Table(title="Comandos disponibles", border_style="dim")
        table.add_column("Comando", style="bold cyan")
        table.add_column("Descripción", style="white")
        table.add_row("/voice [on|off|<nombre>]", "Alternar voz o elegir voz natural (elvira, dalia, ximena, salome)")
        table.add_row("/coworking [on|off]", "Alterna modo equipo multi-agente (EDITH + Scout + Auditor)")
        table.add_row("/sessions", "Muestra historial de conversaciones guardadas")
        table.add_row("/load <id>", "Recupera una charla anterior")
        table.add_row("/new", "Inicia una conversación limpia preservando recuerdos generales")
        table.add_row("/learnings", "Muestra las lecciones aprendidas de errores previos")
        table.add_row("/provider <ollama|gemini>", "Cambia entre modelos locales y en la nube")
        table.add_row("/model <nombre>", "Define el modelo a usar")
        table.add_row("/clear", "Limpia la conversación actual")
        table.add_row("/exit", "Cierra el agente")
        self.console.print(table)
