"""Multi-agent Co-working Team: EDITH (Leader), Scout (Researcher), and Auditor (Critic)."""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable
from ..providers.base import BaseLLMProvider
from ..tools import web_search, read_web_page, save_to_workspace


@dataclass
class TeamMemberEvent:
    member: str
    role: str
    content: str
    action_type: str = "thought"  # thought, search, audit, synthesis


class CoworkingTeam:
    """Orquesta la colaboración táctica entre EDITH, Scout y el Auditor."""

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider

    def _call_llm_step(self, system_instruction: str, user_content: str) -> str:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_content}
        ]
        resp = self.provider.generate_step(messages=messages, tools_metadata=[])
        return resp.content or resp.thought or "Análisis completado."

    def collaborate(
        self,
        objective: str,
        on_event: Optional[Callable[[TeamMemberEvent], None]] = None,
        context: str = ""
    ) -> Dict[str, Any]:
        """
        Ejecuta el protocolo de co-working en 4 fases interactivas.
        """
        def emit(member: str, role: str, content: str, action_type: str = "thought"):
            if on_event:
                on_event(TeamMemberEvent(member=member, role=role, content=content, action_type=action_type))

        # -------------------------------------------------------------
        # FASE 1: EDITH (Líder Táctica) - Deconstrucción y Plan
        # -------------------------------------------------------------
        emit("EDITH", "Líder & Estratega", f"Deconstruyendo objetivo táctico: '{objective}'", "thought")
        
        edith_plan_prompt = (
            "Eres EDITH, líder estratégica de un equipo de co-working de IA. "
            "Tu tarea es analizar el objetivo del usuario mediante razonamiento abstracto y de primeros principios, "
            "definiendo las preguntas esenciales que el investigador ('Scout') debe rastrear en la web y los posibles riesgos a auditar."
        )
        plan = self._call_llm_step(
            edith_plan_prompt,
            f"Objetivo: {objective}\nPor favor define el plan de investigación y qué términos o preguntas clave debe buscar Scout."
            + (f"\n\nContexto recordado del usuario (úsalo solo si es pertinente):\n{context}" if context else "")
        )
        emit("EDITH", "Líder & Estratega", plan, "thought")

        # -------------------------------------------------------------
        # FASE 2: SCOUT (Investigador de Campo) - Búsquedas y Evidencia
        # -------------------------------------------------------------
        emit("Scout", "Investigador Web", "Iniciando barrido de fuentes en internet...", "search")
        
        # Generar consultas optimizadas
        query_generator_prompt = (
            "Eres Scout, especialista en investigación web. Con base en este plan de investigación, "
            "genera exactamente 2 consultas de búsqueda concisas y efectivas para DuckDuckGo. "
            "Devuelve únicamente las 2 consultas separadas por salto de línea."
        )
        queries_text = self._call_llm_step(query_generator_prompt, plan)
        queries = [q.strip("- 12. \t\"") for q in queries_text.splitlines() if q.strip()][:2]
        if not queries:
            queries = [objective]

        raw_findings = []
        sources = []
        for q in queries:
            emit("Scout", "Investigador Web", f"Consultando DuckDuckGo: \"{q}\"", "search")
            res = web_search(q, max_results=3)
            for item in res:
                if isinstance(item, dict) and item.get("url"):
                    sources.append({"title": item.get("title", ""), "url": item.get("url", "")})
                    raw_findings.append(f"Fuente: {item.get('title')}\nEnlace: {item.get('url')}\nResumen: {item.get('snippet')}\n")

        evidence_text = "\n".join(raw_findings) if raw_findings else "No se localizaron fuentes externas relevantes."
        
        # Scout compila su informe de evidencia
        scout_summary_prompt = (
            "Eres Scout. Resume la evidencia fáctica y datos concretos descubiertos en los resultados de búsqueda web. "
            "Sé objetivo, preciso y cita los datos clave."
        )
        scout_report = self._call_llm_step(scout_summary_prompt, f"Evidencia encontrada:\n{evidence_text}")
        emit("Scout", "Investigador Web", scout_report, "search")

        # -------------------------------------------------------------
        # FASE 3: AUDITOR (Crítico Dialéctico) - Auditoría y Contrapuntos
        # -------------------------------------------------------------
        emit("Auditor", "Crítico Dialéctico", "Auditando consistencia lógica, sesgos y lagunas...", "audit")
        
        auditor_prompt = (
            "Eres el Auditor del equipo. Tu función es la dialéctica crítica: analiza el reporte de Scout y el plan inicial. "
            "Detecta inconsistencias, afirmaciones no comprobadas, sesgos o preguntas que aún no han sido respondidas. "
            "Ofrece un veredicto crítico constructivo."
        )
        audit_verdict = self._call_llm_step(
            auditor_prompt,
            f"Objetivo: {objective}\nReporte de Scout:\n{scout_report}"
        )
        emit("Auditor", "Crítico Dialéctico", audit_verdict, "audit")

        # -------------------------------------------------------------
        # FASE 4: EDITH (Líder Táctica) - Síntesis Maestra y Entrega
        # -------------------------------------------------------------
        emit("EDITH", "Líder & Estratega", "Integrando perspectivas para la síntesis final...", "synthesis")
        
        synthesis_prompt = (
            "Eres EDITH. Integra todo el trabajo colaborativo de tu equipo (la evidencia de Scout y la auditoría crítica del Auditor). "
            "Elabora una respuesta maestra definitiva para el usuario: profunda, elocuente, rigurosa y en español claro, "
            "incluyendo conclusiones de alto nivel y fuentes citadas."
        )
        master_answer = self._call_llm_step(
            synthesis_prompt,
            f"Objetivo inicial: {objective}\n\n"
            f"Evidencia de Scout:\n{scout_report}\n\n"
            f"Auditoría del Auditor:\n{audit_verdict}"
        )
        emit("EDITH", "Líder & Estratega", master_answer, "synthesis")

        # Guardar automáticamente el entregable de co-working en workspace
        try:
            workspace_content = (
                f"# Informe de Co-Working: {objective}\n\n"
                f"## 1. Plan Estratégico (EDITH)\n{plan}\n\n"
                f"## 2. Evidencia de Campo (Scout)\n{scout_report}\n\n"
                f"## 3. Auditoría Dialéctica (Auditor)\n{audit_verdict}\n\n"
                f"## 4. Síntesis y Conclusiones Finales (EDITH)\n{master_answer}\n"
            )
            save_to_workspace("informe_coworking_reciente.md", workspace_content)
        except Exception:
            pass

        return {
            "answer": master_answer,
            "plan": plan,
            "scout_report": scout_report,
            "audit_verdict": audit_verdict,
            "sources": sources
        }
