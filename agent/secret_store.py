"""Secretos cifrados en disco con DPAPI de Windows (Fase 14).

Lo que EDITH guarda (token de acceso, clave del bridge y los secretos que se escriben desde
Ajustes en el .env) se cifra con la cuenta de Windows del usuario: otra cuenta de la misma PC,
o alguien que copie el disco o la carpeta de datos, no puede leerlo.

Formato: "dpapi:" + base64. Un valor sin ese prefijo se trata como texto plano (compatibilidad
con .env escritos a mano). Fuera de Windows no hay DPAPI y los valores quedan en texto plano.
"""

import base64
import ctypes
import os
import sys
from ctypes import wintypes

PREFIX = "dpapi:"
_ENTROPY = b"EDITH-secretos-v1"  # liga los datos a EDITH: otro programa no los descifra "por accidente"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _call(fn_name: str, data: bytes) -> bytes:
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = getattr(crypt32, fn_name)
    fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p if fn_name == "CryptUnprotectData" else wintypes.LPCWSTR,
                   ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    data_in, entropy, out = _blob(data), _blob(_ENTROPY), _Blob()
    if not fn(ctypes.byref(data_in), None, ctypes.byref(entropy), None, None, _CRYPTPROTECT_UI_FORBIDDEN,
              ctypes.byref(out)):
        raise OSError(ctypes.get_last_error(), f"{fn_name} falló")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def is_protected(value: str) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def protect(value: str) -> str:
    """Cifra un texto para guardarlo en disco. Vacío o ya cifrado se devuelve tal cual."""
    if not value or is_protected(value) or not available():
        return value
    return PREFIX + base64.b64encode(_call("CryptProtectData", value.encode("utf-8"))).decode("ascii")


def unprotect(value: str) -> str:
    """Descifra un valor "dpapi:…"; si no lleva el prefijo, es texto plano y se devuelve igual.
    Si no se puede descifrar (otra cuenta u otra PC) devuelve "" para que el llamador lo regenere."""
    if not is_protected(value):
        return value
    if not available():
        return ""
    try:
        return _call("CryptUnprotectData", base64.b64decode(value[len(PREFIX):])).decode("utf-8")
    except (OSError, ValueError):
        return ""


def decrypt_environ() -> list:
    """Descifra en os.environ los valores "dpapi:…" que cargó el .env. Devuelve las claves tocadas."""
    keys = [k for k, v in os.environ.items() if is_protected(v)]
    for k in keys:
        os.environ[k] = unprotect(os.environ[k])
    return keys
