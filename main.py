"""Main entrypoint for EDITH: AI Reasoning, Co-Working, Voice, and Web IDE."""

import argparse
import sys
import uvicorn
from agent.cli.ui import AgentCLI
from agent.config import Config


def parse_args():
    parser = argparse.ArgumentParser(
        description="E.D.I.T.H.: Enhanced Dialectical Intelligence & Tactical Heuristics."
    )
    parser.add_argument(
        "--ide",
        action="store_true",
        help="Iniciar EDITH Studio (IDE Web interactivo) en lugar de la consola terminal."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Puerto HTTP para el servidor de EDITH Studio (por defecto 8000)."
    )
    parser.add_argument(
        "--provider",
        type=str,
        choices=["ollama", "gemini"],
        default=None,
        help="Proveedor de IA a utilizar ('ollama' o 'gemini')."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Nombre del modelo (ej. deepseek-r1:latest, gemini-2.5-flash, llama3.2)."
    )
    parser.add_argument(
        "--coworking",
        action="store_true",
        help="Iniciar directamente en modo Co-Working multi-agente."
    )
    parser.add_argument(
        "--no-ml",
        action="store_true",
        help="Desactivar el subsistema de Machine Learning (enrutador y memoria semántica)."
    )
    parser.add_argument(
        "--ml-train",
        action="store_true",
        help="Indexar las sesiones guardadas en data/sessions/ en la memoria semántica y salir."
    )
    parser.add_argument(
        "--ml-status",
        action="store_true",
        help="Mostrar el estado del subsistema ML y salir."
    )
    parser.add_argument(
        "--ml-analyze",
        type=str,
        default=None,
        metavar="TEXTO",
        help="Mostrar qué ruta elegiría el ML y qué recuerdos recuperaría para TEXTO, y salir."
    )
    parser.add_argument(
        "--query", "-q",
        type=str,
        default=None,
        help="Consulta directa para ejecutar sin entrar en el modo interactivo."
    )
    return parser.parse_args()


def start_ide(port: int = 8000):
    print(f"\n👓 Iniciando EDITH Studio (Web IDE)...")
    print(f"👉 Abre tu navegador en: http://localhost:{port}\n")
    uvicorn.run("ide.server:app", host="127.0.0.1", port=port, log_level="info")


def run_ml_tools(args) -> bool:
    """Atiende las opciones --ml-*. Devuelve True si se ejecutó alguna."""
    if not (args.ml_train or args.ml_status or args.ml_analyze):
        return False
    from agent.ml import get_ml_engine

    engine = get_ml_engine()
    if args.ml_train:
        n = engine.train_from_sessions()
        print(f"[ML] {n} mensajes nuevos indexados desde data/sessions/.")
    if args.ml_analyze:
        a = engine.analyze(args.ml_analyze)
        print(f"[ML] Ruta: {a.route} ({a.confidence:.0%})")
        for r, p in sorted(a.probs.items(), key=lambda kv: -kv[1]):
            print(f"      {r:<11}{p:.0%}")
        print(a.context or "[ML] Sin recuerdos relevantes.")
    print(f"[ML] Estado: {engine.status()}")
    return True


def main():
    args = parse_args()

    if run_ml_tools(args):
        return

    if args.no_ml:
        Config.ML_ENABLED = False

    if args.ide:
        start_ide(port=args.port)
        return

    cli = AgentCLI()

    if args.provider or args.model:
        cli.init_agent(provider_name=args.provider, model=args.model)

    if args.coworking:
        cli.coworking_mode = True

    if args.query:
        cli.print_banner()
        cli.run_query(args.query)
    else:
        cli.start_repl()


if __name__ == "__main__":
    main()
