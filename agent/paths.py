"""Rutas de EDITH (Fase 15.1): código por un lado, datos del usuario por otro.

  APP_DIR    -> recursos de la aplicación (código, interfaz, iconos). Solo lectura.
  EDITH_HOME -> datos del usuario: %LOCALAPPDATA%\\EDITH en Windows.
                Sobreviven a actualizaciones y reinstalaciones de la app.
     data/       sesiones, memoria, ML, aprendizajes, canales, recordatorios, audio
     workspace/  archivos compartidos con EDITH (notas, código, capturas)
     logs/       registros de la app de escritorio y del bridge de WhatsApp

La primera vez se COPIAN (no se mueven) data/ y workspace/ de la carpeta del proyecto,
así no se pierde nada de lo anterior. Para pruebas o instalaciones portátiles se puede
fijar otra carpeta con la variable de entorno EDITH_HOME.

App empaquetada (Fase 15.3, PyInstaller en modo carpeta): no hay carpeta de proyecto.
  INSTALL_DIR -> donde están EDITH.exe y edith-whatsapp.exe
  APP_DIR     -> INSTALL_DIR\\_internal (sys._MEIPASS)
  .env        -> siempre el de EDITH_HOME (lo escribe Ajustes)
"""

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))  # True dentro de EDITH.exe (PyInstaller)
# Dentro de un ejecutable de PyInstaller los recursos viven en sys._MEIPASS (_internal\)
APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
PROJECT_DIR = Path(__file__).resolve().parent.parent  # carpeta del código fuente (modo desarrollo)
INSTALL_DIR = Path(sys.executable).resolve().parent if FROZEN else PROJECT_DIR


def read_version() -> str:
    """Versión única de EDITH: el archivo VERSION (raíz del proyecto o _internal en la app)."""
    try:
        return (APP_DIR / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


VERSION = read_version()


def _default_home() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "EDITH"


EDITH_HOME = Path(os.environ.get("EDITH_HOME") or _default_home())
DATA_DIR = EDITH_HOME / "data"
WORKSPACE_DIR = EDITH_HOME / "workspace"
LOGS_DIR = EDITH_HOME / "logs"
_MIGRATION_MARKER = EDITH_HOME / ".migrado_desde_proyecto"

# Cachés regenerables que no vale la pena copiar
_SKIP = {"audio", "__pycache__"}


def _copy_tree_missing(src: Path, dst: Path) -> int:
    """Copia src -> dst sin sobrescribir archivos que ya existan en dst."""
    copied = 0
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if rel.parts and rel.parts[0] in _SKIP:
            continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            copied += 1
    return copied


def migrate_project_data(project_dir: Path, data_dir: Path, workspace_dir: Path, marker: Path) -> int:
    """Copia data/ y workspace/ del proyecto a la carpeta de datos (una sola vez)."""
    if marker.exists():
        return 0
    copied = 0
    for name, dst in (("data", data_dir), ("workspace", workspace_dir)):
        src = project_dir / name
        if src.is_dir() and src.resolve() != dst.resolve():
            copied += _copy_tree_missing(src, dst)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        f"Datos copiados desde {project_dir} el {datetime.now():%Y-%m-%d %H:%M} ({copied} archivos).\n"
        "Las carpetas data/ y workspace/ del proyecto ya no se usan; puedes conservarlas como respaldo.\n",
        encoding="utf-8",
    )
    return copied


def _is_dev_worktree(path: Path) -> bool:
    """Copias de trabajo temporales (git worktrees de .claude/worktrees): sus data/ pueden estar
    desactualizadas, así que nunca deben ser la fuente de la migración de los datos reales."""
    parts = [p.lower() for p in path.resolve().parts]
    return any(a == ".claude" and b == "worktrees" for a, b in zip(parts, parts[1:]))


def adopt_project_env(env_target: Path, marker: Path):
    """App empaquetada en una PC donde antes se usó EDITH desde el código fuente: la primera vez
    copia el .env de ese proyecto (la marca de la migración dice cuál) para conservar los ajustes.
    Devuelve el .env copiado o None."""
    if env_target.exists() or not marker.exists():
        return None
    found = re.search(r"Datos copiados desde (.+?) el \d{4}-\d{2}-\d{2}",
                      marker.read_text(encoding="utf-8", errors="replace"))
    source = Path(found.group(1)) / ".env" if found else None
    if not source or not source.is_file():
        return None
    shutil.copy2(source, env_target)
    return source


def _migrate_from_project() -> None:
    if os.environ.get("EDITH_HOME"):
        return  # carpeta explícita (pruebas, instalación portátil): no se migra nada
    if FROZEN:
        adopt_project_env(EDITH_HOME / ".env", _MIGRATION_MARKER)  # sin proyecto del que copiar data/
        return
    if _is_dev_worktree(PROJECT_DIR):
        return  # la migración se hará la primera vez que EDITH se abra desde la carpeta principal
    migrate_project_data(PROJECT_DIR, DATA_DIR, WORKSPACE_DIR, _MIGRATION_MARKER)


def ensure_dirs() -> None:
    for d in (DATA_DIR, WORKSPACE_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def env_file() -> Path:
    """.env del proyecto si se ejecuta desde el código fuente; en la app empaquetada (o si el
    proyecto no tiene .env), el de EDITH_HOME."""
    project_env = PROJECT_DIR / ".env"
    return project_env if not FROZEN and project_env.exists() else EDITH_HOME / ".env"


EDITH_HOME.mkdir(parents=True, exist_ok=True)
_migrate_from_project()
ensure_dirs()
