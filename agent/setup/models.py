"""Descarga de modelos de Ollama con progreso (Fase 15.2).

Usa /api/pull en modo streaming: Ollama informa bytes descargados por capa y reanuda solo
las descargas que se cortaron, así que "Reintentar" continúa donde se quedó.
"""

import json
import threading
from typing import Any, Dict, List, Optional

import httpx


class PullManager:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self.models: Dict[str, Dict[str, Any]] = {}
        self.order: List[str] = []
        self.on_finish = None  # callable(progress): p. ej. aviso de Windows al terminar (Fase 6)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, models: List[str]) -> bool:
        if self.running:
            return False
        models = [m.strip() for m in dict.fromkeys(models) if m and m.strip()]
        with self._lock:
            self.order = models
            self.models = {m: {"status": "en cola", "completed": 0, "total": 0, "message": ""} for m in models}
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, name="edith-model-pull", daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def progress(self) -> Dict[str, Any]:
        with self._lock:
            items = [{"model": m, **self.models[m]} for m in self.order]
        done = sum(i["completed"] for i in items)
        total = sum(i["total"] for i in items)
        return {
            "running": self.running,
            "items": items,
            "percent": round(100 * done / total, 1) if total else (100.0 if items and all(i["status"] == "listo" for i in items) else 0.0),
            "finished": bool(items) and not self.running,
            "ok": bool(items) and all(i["status"] == "listo" for i in items),
        }

    def _update(self, model: str, **fields):
        with self._lock:
            self.models[model].update(fields)

    def _run(self):
        try:
            self._run_all()
        finally:
            if self.on_finish:
                try:
                    self.on_finish(self.progress_snapshot())
                except Exception:
                    pass

    def progress_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            items = [{"model": m, **self.models[m]} for m in self.order]
        return {"items": items, "ok": bool(items) and all(i["status"] == "listo" for i in items)}

    def _run_all(self):
        from ..providers.ollama_provider import ensure_ollama_running
        if not ensure_ollama_running(self.base_url, timeout=20.0):
            for m in self.order:
                self._update(m, status="error", message="Ollama no está instalado o no arrancó.")
            return
        for model in self.order:
            if self._cancel.is_set():
                self._update(model, status="cancelado")
                continue
            self._pull(model)

    def _pull(self, model: str):
        layers: Dict[str, List[int]] = {}
        self._update(model, status="descargando", message="Conectando…")
        try:
            with httpx.stream("POST", f"{self.base_url}/api/pull", json={"model": model, "stream": True},
                              timeout=httpx.Timeout(60.0, read=600.0)) as resp:
                if resp.status_code != 200:
                    self._update(model, status="error", message=f"Ollama respondió HTTP {resp.status_code}")
                    return
                for line in resp.iter_lines():
                    if self._cancel.is_set():
                        self._update(model, status="cancelado", message="Descarga pausada; se reanuda al reintentar.")
                        return
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    if ev.get("error"):
                        self._update(model, status="error", message=ev["error"])
                        return
                    digest = ev.get("digest")
                    if digest and ev.get("total"):
                        layers[digest] = [int(ev.get("completed") or 0), int(ev["total"])]
                    completed = sum(c for c, _ in layers.values())
                    total = sum(t for _, t in layers.values())
                    status = ev.get("status", "")
                    self._update(model, completed=completed, total=total,
                                 message="Verificando…" if "verif" in status else status[:60])
                    if status == "success":
                        self._update(model, status="listo", message="Descargado", completed=total, total=total)
                        return
        except httpx.HTTPError as e:
            self._update(model, status="error", message=f"Se cortó la conexión ({type(e).__name__}). Reintenta: continúa donde quedó.")
            return
        with self._lock:
            if self.models[model]["status"] == "descargando":
                self.models[model]["status"] = "error"
                self.models[model]["message"] = "La descarga terminó sin confirmación."
