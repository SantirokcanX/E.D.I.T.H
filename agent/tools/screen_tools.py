"""Screen Vision and Display Capture tools for EDITH."""

import os
import sys
import time
import base64
import ctypes
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from PIL import Image, ImageGrab
import psutil

# Directorio de capturas dentro del workspace
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS_DIR = BASE_DIR / "workspace" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _attach_to_input_desktop():
    """Asegura que el hilo esté conectado a la estación de escritorio interactiva en Windows."""
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
        except Exception:
            pass


def get_active_window_info() -> Dict[str, Any]:
    """Obtiene información de la ventana que tiene el foco activo en Windows."""
    if sys.platform != "win32":
        return {"title": "Desconocido", "process": "Desconocido", "pid": None}

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"title": "Escritorio / Sin foco", "process": "explorer.exe", "pid": None}

        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.strip()

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc_name = "desconocido"
        if pid.value:
            try:
                proc_name = psutil.Process(pid.value).name()
            except Exception:
                pass

        return {
            "title": title or "Ventana sin título",
            "process": proc_name,
            "pid": pid.value
        }
    except Exception as e:
        return {"title": f"Error: {e}", "process": "desconocido", "pid": None}


def capture_screen(area: str = "full") -> Dict[str, Any]:
    """
    Captura una imagen de la pantalla de la laptop y la almacena en el workspace.
    
    Args:
        area: 'full' para monitor completo, 'active_window' para la ventana enfocada.
    """
    _attach_to_input_desktop()

    active_info = get_active_window_info()
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"screenshot_{timestamp_str}.png"
    target_path = SCREENSHOTS_DIR / filename
    latest_path = SCREENSHOTS_DIR / "latest_screen.png"

    try:
        img = ImageGrab.grab(all_screens=True)
        img.save(target_path, "PNG")
        img.save(latest_path, "PNG")

        rel_path = f"workspace/screenshots/{filename}"
        url_path = f"/api/workspace/file?path={rel_path}"

        return {
            "status": "success",
            "message": f"Captura realizada exitosamente ({img.width}x{img.height}).",
            "filename": filename,
            "relative_path": rel_path,
            "url": url_path,
            "resolution": f"{img.width}x{img.height}",
            "active_window": active_info["title"],
            "active_process": active_info["process"],
            "timestamp": timestamp_str
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Fallo al capturar la pantalla: {str(e)}"
        }


def analyze_screen(query: Optional[str] = None) -> Dict[str, Any]:
    """
    Toma una captura de pantalla instantánea y la analiza visualmente para responder
    a dudas del usuario sobre lo que está viendo en su laptop.
    
    Args:
        query: Pregunta u objetivo específico (ej. '¿qué error hay en pantalla?', 'analiza este diagrama').
    """
    cap_res = capture_screen(area="full")
    if cap_res.get("status") != "success":
        return cap_res

    image_file = SCREENSHOTS_DIR / cap_res["filename"]
    active_win = cap_res.get("active_window", "")
    active_proc = cap_res.get("active_process", "")

    user_query = query or "Describe y analiza detalladamente lo que se observa en esta pantalla."

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=gemini_key)
            with open(image_file, "rb") as f:
                img_bytes = f.read()

            prompt = (
                f"Estás viendo la pantalla de la laptop del usuario.\n"
                f"Ventana activa en primer plano: '{active_win}' (Proceso: {active_proc}).\n"
                f"Pregunta del usuario: {user_query}\n\n"
                f"Responde de forma clara, directa, reflexiva y en español como EDITH."
            )

            response = client.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
                contents=[
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                    prompt
                ]
            )

            cap_res["visual_analysis"] = response.text.strip()
            cap_res["analyzed_by"] = "gemini-multimodal"
            return cap_res
        except Exception as e:
            cap_res["analysis_warning"] = f"Análisis multimodal con Gemini no disponible: {e}"

    cap_res["visual_analysis"] = (
        f"Se ha capturado la pantalla completa ({cap_res['resolution']}).\n"
        f"- **Ventana activa**: `{active_win}`\n"
        f"- **Aplicación en foco**: `{active_proc}`\n"
        f"- **Archivo guardado**: `{cap_res['relative_path']}`\n\n"
        f"La imagen está disponible en el panel de trabajo. Puedes pedirme revisar detalles de la ventana o realizar acciones sobre la misma."
    )
    cap_res["analyzed_by"] = "local-context"
    return cap_res
