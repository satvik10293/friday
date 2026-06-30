"""
core/launcher/health.py — FRIDAY V3 (M20)
Runtime health + diagnostics. Aggregates the health of the cognitive machinery — the
service kernel, runtime/event bus, the Cognitive Brains, the Coordinator, the Simulation
Brain — plus process vitals (threads, CPU, RAM via psutil when present). One `diagnostics()`
call gives operators a single, never-raises status picture.
"""

from __future__ import annotations

import importlib.util
import threading


class HealthMonitor:
    def __init__(self, *, container=None, runtime=None, coordinator=None,
                 simulation=None) -> None:
        self._container = container
        self._runtime = runtime
        self._coordinator = coordinator
        self._simulation = simulation

    # ── system vitals ────────────────────────────────────────────────────────────
    @staticmethod
    def system() -> dict:
        out = {"threads": threading.active_count()}
        if importlib.util.find_spec("psutil") is not None:
            try:
                import psutil
                out["cpu_percent"] = psutil.cpu_percent(interval=0.0)
                vm = psutil.virtual_memory()
                out["ram_percent"] = vm.percent
                out["ram_available_mb"] = round(vm.available / 1_048_576, 1)
            except Exception:  # noqa: BLE001
                out["psutil"] = "error"
        else:
            out["psutil"] = "absent"
        return out

    # ── full diagnostics ─────────────────────────────────────────────────────────
    def diagnostics(self) -> dict:
        report: dict = {"system": self.system(), "services": {}, "subsystems": {}}
        if self._container is not None and hasattr(self._container, "health"):
            report["services"] = _safe(self._container.health, {})
        if self._runtime is not None and hasattr(self._runtime, "health"):
            report["subsystems"]["runtime"] = _safe(self._runtime.health, {})
        if self._coordinator is not None and hasattr(self._coordinator, "health"):
            report["subsystems"]["coordinator"] = _safe(self._coordinator.health, {})
        if self._simulation is not None and hasattr(self._simulation, "health"):
            report["subsystems"]["simulation"] = _safe(self._simulation.health, {})
        report["status"] = self._overall(report)
        return report

    @staticmethod
    def _overall(report: dict) -> str:
        statuses = []
        svc = report.get("services", {})
        if isinstance(svc, dict):
            statuses.append(svc.get("status", "ok"))
        for h in report.get("subsystems", {}).values():
            if isinstance(h, dict):
                statuses.append(h.get("status", "ok"))
        return "degraded" if any(s not in ("ok", "placeholder", "absent", "disabled")
                                 for s in statuses) else "ok"

    def status(self) -> str:
        return self.diagnostics()["status"]


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default
