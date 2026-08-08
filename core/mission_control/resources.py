"""
core/mission_control/resources.py — FRIDAY 4.0 (M10)
Resource monitor: CPU · RAM · GPU · disk · database health · model health. Uses
psutil when available and degrades to "unavailable" fields when it isn't (never
crashes). Database + model health compose the M10 migration framework and the
model registry.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("friday.mission_control.resources")

_ROOT = Path(__file__).resolve().parents[2]
_DATA = _ROOT / "data"

# DBs FRIDAY maintains (known set; missing ones are simply "absent", not errors).
_KNOWN_DBS = ("memory.db", "knowledge.db", "user_model.db", "goals.db",
              "world.db", "cognition.db", "perception.db", "decisions.db",
              "audit.db", "security.db", "auth.db")


def _psutil():
    if importlib.util.find_spec("psutil") is None:
        return None
    import psutil
    return psutil


class ResourceMonitor:
    def __init__(self, *, model_registry=None) -> None:
        self._model_registry = model_registry

    # ── compute ─────────────────────────────────────────────────────────────────
    def system(self) -> dict:
        ps = _psutil()
        if ps is None:
            return {"available": False, "note": "psutil not installed"}
        try:
            vm = ps.virtual_memory()
            disk = ps.disk_usage(str(_ROOT))
            out = {
                "available": True,
                "cpu_percent": ps.cpu_percent(interval=0.0),
                "cpu_count": ps.cpu_count(),
                "ram_percent": vm.percent,
                "ram_used_mb": round(vm.used / 1024 / 1024, 1),
                "ram_total_mb": round(vm.total / 1024 / 1024, 1),
                "disk_percent": disk.percent,
                "disk_free_gb": round(disk.free / 1024 / 1024 / 1024, 1),
                "gpu": self._gpu(),
            }
            return out
        except Exception as e:  # noqa: BLE001
            return {"available": False, "error": str(e)}

    def _gpu(self) -> dict:
        # CPU-only build: report absence rather than pretending. (A future GPU
        # backend can populate this without changing callers.)
        if importlib.util.find_spec("pynvml") is not None:
            try:
                import pynvml
                pynvml.nvmlInit()
                n = pynvml.nvmlDeviceGetCount()
                return {"present": n > 0, "count": n}
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        return {"present": False, "note": "CPU-only"}

    # ── databases ───────────────────────────────────────────────────────────────
    def databases(self) -> dict:
        dbs = []
        for name in _KNOWN_DBS:
            p = _DATA / name
            if p.exists():
                dbs.append({"name": name, "present": True,
                            "size_kb": round(p.stat().st_size / 1024, 1)})
            else:
                dbs.append({"name": name, "present": False})
        present = [d for d in dbs if d["present"]]
        return {"count": len(present), "databases": dbs,
                "total_kb": round(sum(d.get("size_kb", 0) for d in present), 1)}

    # ── models ──────────────────────────────────────────────────────────────────
    def models(self) -> dict:
        if self._model_registry is None:
            try:
                from core.infra.model_registry import get_model_registry
                self._model_registry = get_model_registry()
            except Exception:
                return {"available": False}
        try:
            return {"available": True, **self._model_registry.health()}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "error": str(e)}

    # ── snapshot ────────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {"system": self.system(), "databases": self.databases(),
                "models": self.models()}

    def health(self) -> dict:
        sysinfo = self.system()
        status = "ok"
        if sysinfo.get("available"):
            if sysinfo.get("ram_percent", 0) > 92 or sysinfo.get("disk_percent", 0) > 95:
                status = "pressure"
        return {"status": status, "psutil": sysinfo.get("available", False)}
