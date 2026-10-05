"""EDITH Native Desktop Application (pywebview wrapper).
Runs EDITH as a standalone Windows desktop app like Claude or ChatGPT Desktop.
"""

import sys
import os
import time
import threading
from pathlib import Path
import webview
import uvicorn

# Asegurar que el directorio raíz del proyecto esté en el sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PORT = 8000
SERVER_URL = f"http://127.0.0.1:{PORT}"


def start_server():
    """Ejecuta el servidor FastAPI en un hilo en segundo plano."""
    uvicorn.run("ide.server:app", host="127.0.0.1", port=PORT, log_level="warning")


def main():
    # 1. Iniciar servidor backend en segundo plano
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Pequeña pausa para asegurar que el servidor esté activo
    time.sleep(1.2)

    # 2. Configurar y lanzar la ventana nativa de escritorio
    window = webview.create_window(
        title="EDITH — AI Companion, System Control & Visual Intelligence",
        url=SERVER_URL,
        width=1320,
        height=880,
        min_size=(960, 640),
        background_color="#0a0e17"
    )

    # 3. Iniciar el bucle de la aplicación nativa
    webview.start(debug=False)


if __name__ == "__main__":
    main()
