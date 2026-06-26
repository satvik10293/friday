"""
core/intelligence/health_monitor.py — FRIDAY 4.0 (M12)
Model + system health monitoring (Part 12). Tracks per-model latency and failures,
declares a model unhealthy after consecutive failures (so the manager can restart
it), reports system resources (CPU/RAM/GPU/temperature via psutil when available),
and notifies a callback (Mission Control) on health changes.
"""

from __future__ import annotations

import importlib.util
import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

log = logging.getLogger("friday.intelligence.health")


@dataclass
class ModelHealth:
    name: str
    failures: int = 0
    consecutive_failures: int = 0
    successes: int = 0
    last_latency_ms: float = 0.0
    healthy: bool = True

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _psutil():
    if importlib.util.find_spec("psutil") is None:
        return None
    import psutil
    return psutil


class HealthMonitor:
    def __init__(self, *, fail_threshold: int = 3,
                 notify: Optional[Callable[[str, dict], None]] = None) -> None:
        self._fail_threshold = fail_threshold
        self._notify = notify
        self._models: dict[str, ModelHealth] = {}
        self._lock = threading.Lock()

    # ── per-model ───────────────────────────────────────────────────────────────
    def record(self, name: str, *, success: bool, latency_ms: float = 0.0) -> ModelHealth:
        with self._lock:
            mh = self._models.setdefault(name, ModelHealth(name=name))
            mh.last_latency_ms = latency_ms
            if success:
                mh.successes += 1
                mh.consecutive_failures = 0
                if not mh.healthy:
                    mh.healthy = True
                    self._emit(name, mh)
            else:
                mh.failures += 1
                mh.consecutive_failures += 1
                if mh.consecutive_failures >= self._fail_threshold and mh.healthy:
                    mh.healthy = False
                    log.warning("model %s declared unhealthy (%d consecutive failures)",
                                name, mh.consecutive_failures)
                    self._emit(name, mh)
            return mh

    def reset(self, name: str) -> None:
        with self._lock:
            mh = self._models.get(name)
            if mh is not None:
                mh.consecutive_failures = 0
                mh.healthy = True

    def is_healthy(self, name: str) -> bool:
        mh = self._models.get(name)
        return mh.healthy if mh else True

    def unhealthy_models(self) -> list[str]:
        return [n for n, mh in self._models.items() if not mh.healthy]

    def model_report(self) -> list[dict]:
        return [mh.to_dict() for mh in self._models.values()]

    def _emit(self, name: str, mh: ModelHealth) -> None:
        if self._notify:
            try:
                self._notify(name, mh.to_dict())
            except Exception:  # noqa: BLE001
                pass

    # ── system ──────────────────────────────────────────────────────────────────
    def system(self) -> dict:
        ps = _psutil()
        if ps is None:
            return {"available": False}
        try:
            vm = ps.virtual_memory()
            temps = {}
            if hasattr(ps, "sensors_temperatures"):
                try:
                    raw = ps.sensors_temperatures() or {}
                    temps = {k: (v[0].current if v else None) for k, v in raw.items()}
                except Exception:  # noqa: BLE001
                    temps = {}
            return {"available": True, "cpu_percent": ps.cpu_percent(interval=0.0),
                    "ram_percent": vm.percent, "gpu": self._gpu(), "temperature": temps}
        except Exception as e:  # noqa: BLE001
            return {"available": False, "error": str(e)}

    @staticmethod
    def _gpu() -> dict:
        if importlib.util.find_spec("pynvml") is not None:
            try:
                import pynvml
                pynvml.nvmlInit()
                return {"present": pynvml.nvmlDeviceGetCount() > 0}
            except Exception:  # noqa: BLE001
                pass
        return {"present": False, "note": "CPU-only"}

    def health(self) -> dict:
        unhealthy = self.unhealthy_models()
        return {"status": "ok" if not unhealthy else "degraded",
                "unhealthy": unhealthy, "monitored": len(self._models),
                "system": self.system()}
