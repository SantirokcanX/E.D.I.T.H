"""Automatización de teclado (Fase 5): escribir texto y pulsar atajos en una ventana de la laptop.

Una sola herramienta con todos los pasos, para que el usuario autorice la secuencia completa de una
vez (Fase 14: siempre pide confirmación). Medidas de seguridad:
  - Hay que decir en qué ventana (parte del título). Si no existe, no se escribe nada.
  - Antes de cada paso se comprueba que esa ventana siga al frente: si el usuario cambia de
    ventana, EDITH se detiene en ese paso (no escribe en otro sitio).
  - Nunca escribe en la propia ventana de EDITH.
  - Límites: 60 pasos, 4000 caracteres en total y esperas de 10 s como máximo.
"""

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional, Tuple

MAX_STEPS = 60
MAX_CHARS = 4000
MAX_WAIT_MS = 10_000

VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B, "windows": 0x5B,
    "enter": 0x0D, "intro": 0x0D, "return": 0x0D, "tab": 0x09, "esc": 0x1B, "escape": 0x1B,
    "backspace": 0x08, "retroceso": 0x08, "delete": 0x2E, "supr": 0x2E, "insert": 0x2D,
    "space": 0x20, "espacio": 0x20, "up": 0x26, "arriba": 0x26, "down": 0x28, "abajo": 0x28,
    "left": 0x25, "izquierda": 0x25, "right": 0x27, "derecha": 0x27, "home": 0x24, "inicio": 0x24,
    "end": 0x23, "fin": 0x23, "pageup": 0x21, "pagedown": 0x22, "capslock": 0x14,
    "printscreen": 0x2C, "menu": 0x5D,
}
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
MODIFIERS = {0x11, 0x10, 0x12, 0x5B}
EXTENDED = {0x2E, 0x2D, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x5B, 0x5D}

KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4
INPUT_KEYBOARD = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):  # solo para que la unión tenga el tamaño correcto
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    u.SendInput.restype = wintypes.UINT
    return u


def parse_keys(spec: str) -> List[int]:
    """'ctrl+shift+s' -> [VK_CONTROL, VK_SHIFT, 'S']. Lanza ValueError si una tecla no existe."""
    codes = []
    for part in [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]:
        if part in VK:
            codes.append(VK[part])
        elif len(part) == 1 and (part.isalnum()):
            codes.append(ord(part.upper()))
        else:
            raise ValueError(f"Tecla desconocida: «{part}»")
    if not codes:
        raise ValueError("Combinación vacía")
    return codes


def _key_event(vk: int, up: bool) -> _INPUT:
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    return _INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(vk, 0, flags, 0, 0)))


def _char_events(ch: str) -> List[_INPUT]:
    events = []
    data = ch.encode("utf-16-le")
    for i in range(0, len(data), 2):  # caracteres fuera del BMP (emojis) van en dos unidades
        unit = int.from_bytes(data[i:i + 2], "little")
        for up in (False, True):
            flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
            events.append(_INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=_KEYBDINPUT(0, unit, flags, 0, 0))))
    return events


def _send(events: List[_INPUT]):
    if not events:
        return
    arr = (_INPUT * len(events))(*events)
    if _user32().SendInput(len(events), arr, ctypes.sizeof(_INPUT)) != len(events):
        raise OSError("Windows no aceptó la pulsación (¿ventana con permisos de administrador?)")


def press_combo(codes: List[int]):
    _send([_key_event(c, False) for c in codes] + [_key_event(c, True) for c in reversed(codes)])


def type_text(text: str):
    for line_i, line in enumerate(text.split("\n")):
        if line_i:
            press_combo([VK["enter"]])
        events = []
        for ch in line.replace("\r", ""):
            events.extend(_char_events(ch))
        for i in range(0, len(events), 200):  # en tandas: algunas apps pierden teclas si llegan miles de golpe
            _send(events[i:i + 200])
            time.sleep(0.01)


# ---------------------------------------------------------------- ventanas
def _windows() -> List[Tuple[int, str]]:
    u = _user32()
    found = []
    CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(h, _):
        if u.IsWindowVisible(h):
            n = u.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(h, buf, n + 1)
                found.append((h, buf.value))
        return True
    u.EnumWindows(CB(cb), 0)
    return found


def _is_edith(title: str) -> bool:
    return title.strip() == "EDITH" or title.startswith("EDITH —") or title.startswith("EDITH -")


def find_window(target: str) -> Optional[Tuple[int, str]]:
    t = (target or "").strip().lower()
    if not t:
        return None
    matches = [(h, title) for h, title in _windows() if t in title.lower() and not _is_edith(title)]
    return matches[0] if matches else None


def _focus(hwnd: int) -> bool:
    u = _user32()
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # SW_RESTORE
    # Windows solo deja cambiar el primer plano a quien recibió la última entrada: un Alt "vacío" lo permite
    _send([_key_event(VK["alt"], False), _key_event(VK["alt"], True)])
    u.SetForegroundWindow(hwnd)
    for _ in range(20):
        if u.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.05)
    return False


def describe_steps(steps: List[Dict[str, Any]]) -> str:
    out = []
    for s in steps or []:
        a, v = s.get("action"), str(s.get("value", ""))
        out.append({"type": f"escribir «{v[:80]}»", "keys": f"pulsar {v}", "wait": f"esperar {v} ms"}.get(a, f"{a} {v}"))
    return "; ".join(out)


def validate_steps(steps: Any) -> Optional[str]:
    if not isinstance(steps, list) or not steps:
        return "No hay pasos que hacer."
    if len(steps) > MAX_STEPS:
        return f"Demasiados pasos ({len(steps)}); el máximo es {MAX_STEPS}."
    chars = 0
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict) or s.get("action") not in ("type", "keys", "wait"):
            return f"Paso {i}: la acción debe ser 'type', 'keys' o 'wait'."
        v = str(s.get("value", ""))
        if s["action"] == "keys":
            try:
                parse_keys(v)
            except ValueError as e:
                return f"Paso {i}: {e}"
        elif s["action"] == "wait":
            if not v.isdigit() or int(v) > MAX_WAIT_MS:
                return f"Paso {i}: la espera debe ser un número de milisegundos (máximo {MAX_WAIT_MS})."
        else:
            chars += len(v)
    if chars > MAX_CHARS:
        return f"Demasiado texto ({chars} caracteres); el máximo es {MAX_CHARS}."
    return None


def keyboard_actions(target_window: str = "", steps: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if sys.platform != "win32":
        return {"error": "La automatización de teclado solo funciona en Windows."}
    problem = validate_steps(steps)
    if problem:
        return {"error": problem}
    win = find_window(target_window)
    if not win:
        titles = [t for _, t in _windows() if not _is_edith(t)][:12]
        return {"error": f"No encontré una ventana cuyo título contenga «{target_window}». "
                         "No escribí nada. Ventanas abiertas: " + "; ".join(titles)}
    hwnd, title = win
    if not _focus(hwnd):
        return {"error": f"No pude traer al frente «{title}». No escribí nada."}
    u = _user32()
    done = 0
    for i, step in enumerate(steps, 1):
        if u.GetForegroundWindow() != hwnd:
            return {"status": "detenido", "window": title, "steps_done": done,
                    "message": f"Te cambiaste de ventana: me detuve antes del paso {i} para no escribir en otro sitio."}
        action, value = step["action"], str(step.get("value", ""))
        if action == "type":
            type_text(value)
        elif action == "keys":
            press_combo(parse_keys(value))
        else:
            time.sleep(int(value) / 1000)
        done += 1
        time.sleep(0.05)
    return {"status": "hecho", "window": title, "steps_done": done}


KEYBOARD_TOOLS_METADATA = [
    {
        "name": "keyboard_actions",
        "description": ("Escribe texto y pulsa teclas o atajos en una ventana abierta de la laptop, para tareas "
                        "repetitivas (rellenar campos, escribir un texto en el Bloc de notas, Ctrl+S...). Manda TODOS "
                        "los pasos en una sola llamada: el usuario autoriza la secuencia completa."),
        "parameters": {
            "type": "object",
            "properties": {
                "target_window": {"type": "string",
                                  "description": "Parte del título de la ventana donde escribir (ej. 'Bloc de notas', 'Excel', 'Word')."},
                "steps": {
                    "type": "array",
                    "description": "Pasos en orden. action='type' escribe value; 'keys' pulsa un atajo (ej. 'ctrl+s', 'enter', 'alt+tab'); 'wait' espera value milisegundos.",
                    "items": {"type": "object",
                              "properties": {"action": {"type": "string", "enum": ["type", "keys", "wait"]},
                                             "value": {"type": "string"}},
                              "required": ["action", "value"]},
                },
            },
            "required": ["target_window", "steps"],
        },
    },
]
