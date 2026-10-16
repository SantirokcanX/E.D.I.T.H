"""Coordinación entre canales: un solo modelo local atiende interfaz, WhatsApp, llamadas y Heartbeat.

Sin este candado, dos peticiones simultáneas competirían por la misma GPU (y en una GPU de
6 GB pueden forzar a Ollama a recargar modelos), lo que haría ambas respuestas más lentas.
"""

import threading

LLM_LOCK = threading.RLock()
