"""Diagnóstico del equipo para recomendar modelos (Fase 15.2)."""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import psutil

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0

# Tamaño aproximado de descarga (GB) de los modelos que EDITH sabe recomendar
MODEL_SIZES_GB = {
    "qwen3:0.6b": 0.5,
    "qwen3:1.7b": 1.4,
    "qwen3:4b-instruct": 2.5,
    "qwen3:4b": 2.5,
    "qwen3:8b": 5.2,
    "qwen3:14b": 9.3,
    "qwen3:32b": 20.2,
}
# qwen3:4b en Ollama es la variante "Thinking-2507": siempre razona, por eso no sirve como modelo rápido.
# qwen3:8b/14b/32b son híbridos: el mismo modelo responde rápido (think=false) o razona.
TIERS = [
    # (VRAM mínima, rápido, profundo, explicación)
    (24, "qwen3:14b", "qwen3:32b", "GPU de 24 GB o más: modelos grandes para ambos modos."),
    (16, "qwen3:8b", "qwen3:14b", "GPU de 16 GB: 8B para responder rápido y 14B para pensar a fondo."),
    (10, "qwen3:8b", "qwen3:8b", "GPU de 10-12 GB: Qwen3 8B híbrido sirve para los dos modos sin cambiar de modelo."),
    (4, "qwen3:4b-instruct", "qwen3:4b", "GPU de 4-8 GB: los dos Qwen3 4B caben enteros en la GPU (rápido ~1 s)."),
    (0, "qwen3:1.7b", "qwen3:4b", "Sin GPU dedicada: modelo pequeño para responder; el modo profundo será lento."),
]


def _run(cmd: List[str], timeout: float = 6.0) -> Optional[str]:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=_NO_WINDOW)
        return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _is_dedicated(name: str) -> bool:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or " rtx" in n:
        return True
    if "radeon" in n and (" rx " in f" {n} " or "rx " in n or "pro w" in n):
        return True
    if "intel" in n and "arc" in n:
        return True
    return False


def gpus() -> List[Dict[str, Any]]:
    """GPUs con su VRAM. nvidia-smi para NVIDIA; registro de Windows para el resto."""
    found: List[Dict[str, Any]] = []
    smi = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader,nounits"])
    if smi:
        for line in smi.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 3:
                found.append({"name": parts[0], "vram_gb": round(float(parts[1]) / 1024, 1),
                              "vram_free_gb": round(float(parts[2]) / 1024, 1), "dedicated": True,
                              "driver": parts[3] if len(parts) > 3 else None, "source": "nvidia-smi"})
    if sys.platform == "win32":
        try:
            import winreg
            base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
                for i in range(64):
                    try:
                        sub = winreg.EnumKey(root, i)
                    except OSError:
                        break
                    if not sub.isdigit():
                        continue
                    try:
                        with winreg.OpenKey(root, sub) as k:
                            name = str(winreg.QueryValueEx(k, "DriverDesc")[0])
                            try:
                                mem = int(winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0])
                            except OSError:
                                raw = winreg.QueryValueEx(k, "HardwareInformation.MemorySize")[0]
                                mem = int.from_bytes(raw, "little") if isinstance(raw, bytes) else int(raw)
                    except OSError:
                        continue
                    if any(name.lower() == g["name"].lower() for g in found) or "basic" in name.lower():
                        continue
                    found.append({"name": name, "vram_gb": round(mem / 1024 ** 3, 1), "vram_free_gb": None,
                                  "dedicated": _is_dedicated(name), "driver": None, "source": "registro"})
        except OSError:
            pass
    return found


def cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                return str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def ollama_models_dir() -> Path:
    custom = os.environ.get("OLLAMA_MODELS")
    return Path(custom) if custom else Path.home() / ".ollama" / "models"


def disk(path: Path) -> Dict[str, Any]:
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    usage = shutil.disk_usage(p)
    return {"path": str(path), "drive": p.anchor or str(p), "free_gb": round(usage.free / 1024 ** 3, 1),
            "total_gb": round(usage.total / 1024 ** 3, 1)}


def ollama_status(base_url: str) -> Dict[str, Any]:
    exe = shutil.which("ollama")
    if not exe and sys.platform == "win32":
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        exe = str(candidate) if candidate.exists() else None
    status: Dict[str, Any] = {"installed": bool(exe), "running": False, "version": None, "models": []}
    try:
        status["version"] = httpx.get(f"{base_url}/api/version", timeout=2).json().get("version")
        status["running"] = True
        tags = httpx.get(f"{base_url}/api/tags", timeout=4).json().get("models", [])
        status["models"] = [{"name": m.get("name"), "size_gb": round(m.get("size", 0) / 1024 ** 3, 1)} for m in tags]
    except Exception:
        pass
    return status


def recommend(best_vram_gb: float, dedicated: bool, ram_gb: float) -> Dict[str, Any]:
    vram = best_vram_gb if dedicated else 0
    for min_vram, fast, deep, why in TIERS:
        if vram >= min_vram:
            break
    if ram_gb < 8 and fast != "qwen3:1.7b":  # poca RAM: bajar un escalón
        fast, deep, why = "qwen3:1.7b", "qwen3:4b", "Menos de 8 GB de RAM: modelos pequeños para no saturar el equipo."
    return {"fast": fast, "deep": deep, "why": why}


def installed_names(models: List[Dict[str, Any]]) -> set:
    names = set()
    for m in models:
        n = m.get("name") or ""
        names.add(n)
        if n.endswith(":latest"):
            names.add(n[: -len(":latest")])
    return names


def diagnose(base_url: str, wanted: Optional[List[str]] = None) -> Dict[str, Any]:
    gpu_list = gpus()
    dedicated = [g for g in gpu_list if g["dedicated"]]
    best = max(dedicated or gpu_list, key=lambda g: g["vram_gb"], default=None)
    ram_gb = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    rec = recommend(best["vram_gb"] if best else 0, bool(dedicated), ram_gb)
    ollama = ollama_status(base_url)
    have = installed_names(ollama["models"])
    wanted = wanted or [rec["fast"], rec["deep"]]
    missing = [m for m in dict.fromkeys(wanted) if m and m not in have]
    need_gb = round(sum(MODEL_SIZES_GB.get(m, 5.0) for m in missing), 1)
    models_disk = disk(ollama_models_dir())
    return {
        "system": {"os": f"{platform.system()} {platform.release()}", "cpu": cpu_name(),
                   "cores": psutil.cpu_count(logical=True), "ram_gb": ram_gb},
        "gpus": gpu_list,
        "best_gpu": best,
        "recommendation": rec,
        "ollama": ollama,
        "models_needed": missing,
        "download_gb": need_gb,
        "models_disk": models_disk,
        "disk_ok": models_disk["free_gb"] >= need_gb + 2,
        "model_sizes_gb": MODEL_SIZES_GB,
    }
