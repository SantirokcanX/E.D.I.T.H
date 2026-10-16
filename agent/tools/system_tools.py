"""Laptop OS manipulation and Computer Control tools for EDITH."""

import os
import shutil
import subprocess
import ctypes
from typing import Dict, Any, Optional
import psutil

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # solo existe en Windows

# Nombres conocidos -> qué se abre. Los botones del panel "Laptop" solo pueden lanzar estos.
APP_ALIASES = {
    "calc": "calc.exe",
    "calculadora": "calc.exe",
    "notepad": "notepad.exe",
    "bloc de notas": "notepad.exe",
    "chrome": "chrome.exe",
    "navegador": "https://www.google.com",
    "spotify": "spotify",
    "explorer": "explorer.exe",
    "archivos": "explorer.exe",
    "vscode": "code",
    "code": "code",
    "terminal": "powershell.exe",
    "powershell": "powershell.exe",
    "cmd": "cmd.exe",
    "paint": "mspaint.exe",
}


def open_application(app_name: str) -> str:
    """
    Abre una aplicación instalada en la laptop de Windows.
    Ejemplos: 'calc', 'notepad', 'chrome', 'spotify', 'explorer', 'code'.

    Sin shell: el nombre nunca se interpreta como una línea de comandos (antes, con shell=True,
    "notepad & del archivo" ejecutaba también el borrado). Se abre con ShellExecute
    (os.startfile), que resuelve programas del PATH, "App Paths" (chrome.exe), URLs y archivos.
    """
    name = app_name.strip()
    target = APP_ALIASES.get(name.lower(), name)
    if not target:
        return "No se indicó qué aplicación abrir."

    try:
        path = shutil.which(target)
        if path and path.lower().endswith((".cmd", ".bat")):
            # Lanzadores de consola (p. ej. code.cmd de VS Code): sin argumentos, sin shell y sin ventana negra
            subprocess.Popen([path], creationflags=NO_WINDOW)
        else:
            os.startfile(path or target)
        return f"Aplicación '{app_name}' iniciada correctamente en tu laptop."
    except Exception as e:
        return f"No se pudo iniciar '{app_name}': {str(e)}"


def get_system_status() -> Dict[str, Any]:
    """
    Obtiene métricas en tiempo real del hardware de la laptop: batería, CPU, memoria RAM y disco.
    """
    # Batería
    battery = psutil.sensors_battery()
    battery_info = {
        "present": battery is not None,
        "percent": f"{battery.percent}%" if battery else "N/A",
        "plugged": battery.power_plugged if battery else False
    }

    # CPU & RAM
    cpu_percent = psutil.cpu_percent(interval=0.2)
    memory = psutil.virtual_memory()
    ram_info = {
        "total_gb": round(memory.total / (1024 ** 3), 1),
        "used_gb": round(memory.used / (1024 ** 3), 1),
        "percent": f"{memory.percent}%"
    }

    # Disco C:
    disk = psutil.disk_usage("C:\\")
    disk_info = {
        "total_gb": round(disk.total / (1024 ** 3), 1),
        "free_gb": round(disk.free / (1024 ** 3), 1),
        "percent_used": f"{disk.percent}%"
    }

    return {
        "bateria": battery_info,
        "cpu_uso": f"{cpu_percent}%",
        "memoria_ram": ram_info,
        "disco_c": disk_info
    }


def run_system_command(command: str) -> str:
    """
    Ejecuta un comando en PowerShell si el usuario lo ordena para manipular el sistema.
    """
    # Filtro básico de seguridad para comandos destructivos
    dangerous_keywords = ["format ", "del /f /s /q c:", "rmdir /s /q c:\\windows", "bcdedit"]
    for d in dangerous_keywords:
        if d in command.lower():
            return f"Comando denegado por seguridad: contiene patrones críticos '{d}'."

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=NO_WINDOW,  # EDITH corre sin consola: que no parpadee una ventana negra
        )
        output = proc.stdout if proc.stdout else proc.stderr
        output = output.strip()
        if len(output) > 2500:
            output = output[:2500] + "\n... [Salida truncada]"
        return output if output else "Comando ejecutado con código de salida 0."
    except Exception as e:
        return f"Error ejecutando comando en la laptop: {str(e)}"


def control_system_volume(action: str) -> str:
    """
    Controla el volumen de la laptop.
    Acciones: 'up' (subir), 'down' (bajar), 'mute' (silenciar/reactivar).
    """
    action = action.lower().strip()
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF

    try:
        if action in ("up", "subir", "+"):
            for _ in range(5):
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 2, 0)
            return "Volumen aumentado en la laptop."
        elif action in ("down", "bajar", "-"):
            for _ in range(5):
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 2, 0)
            return "Volumen reducido en la laptop."
        elif action in ("mute", "silenciar", "mutear"):
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 2, 0)
            return "Silencio (Mute) alternado en la laptop."
        else:
            return f"Acción de volumen no reconocida: '{action}'. Opciones: 'up', 'down', 'mute'."
    except Exception as e:
        return f"Error controlando volumen: {str(e)}"


SYSTEM_TOOLS_METADATA = [
    {
        "name": "open_application",
        "description": "Abre o ejecuta una aplicación o programa en la laptop del usuario (ej. calc, notepad, chrome, spotify, explorer, vscode, paint).",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Nombre de la aplicación a abrir (ej. 'chrome', 'calc', 'notepad', 'spotify')."
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "get_system_status",
        "description": "Consulta el estado en tiempo real del hardware de la laptop: nivel de batería, uso de CPU, memoria RAM disponible y espacio en disco.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "run_system_command",
        "description": "Ejecuta un comando en PowerShell de Windows en la laptop del usuario cuando este te ordene una acción de terminal o sistema.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "El comando de PowerShell a ejecutar."
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "control_system_volume",
        "description": "Controla el volumen del sonido de la laptop ('up' para subir, 'down' para bajar, 'mute' para silenciar).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Acción a realizar: 'up', 'down' o 'mute'."
                }
            },
            "required": ["action"]
        }
    }
]
