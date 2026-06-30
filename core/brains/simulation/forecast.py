"""
core/brains/simulation/forecast.py — FRIDAY V3 (M19)
The Forecast Engine. Estimates the resource + time cost of a scenario BEFORE execution:
CPU, memory, storage, network, duration, automation complexity, and overall system load.
Heuristic and deterministic (action-type + step-count signatures); a learned forecaster
can replace it via the `ForecasterProtocol`. If a runtime service is injected it folds in
the current system load. Every forecast carries a confidence.
"""

from __future__ import annotations

from .interfaces import Forecast, Scenario, SimulationRequest

# per-action-family base cost signatures: (cpu, memory_mb, storage_mb, network, base_s)
_SIGNATURES = {
    "delete": (0.1, 20, 0.0, 0.0, 0.3),
    "backup": (0.2, 50, 200.0, 0.0, 1.5),
    "download": (0.2, 60, 100.0, 0.8, 2.0),
    "upload": (0.2, 60, 0.0, 0.8, 2.0),
    "send": (0.1, 20, 0.0, 0.5, 0.5),
    "compute": (0.7, 200, 0.0, 0.0, 1.0),
    "search": (0.3, 80, 0.0, 0.2, 0.5),
    "open": (0.1, 30, 0.0, 0.0, 0.2),
    "generic": (0.2, 40, 0.0, 0.1, 0.4),
}


class ForecastEngine:
    def __init__(self, *, runtime=None) -> None:
        self._runtime = runtime          # optional: read current system load

    def forecast(self, scenario: Scenario, request: SimulationRequest) -> Forecast:
        cpu, mem, storage, net, base = _signature(request.action)
        steps = max(1, len(scenario.steps))
        complexity = min(1.0, steps / 8.0)
        # cautious scenarios (backup/checks) cost a bit more time + storage
        backup = "backup" in scenario.tags
        duration = base * steps * (1.4 if backup else 1.0)
        storage_mb = storage + (200.0 if backup else 0.0)
        load_now = self._current_load()
        system_load = min(1.0, load_now + cpu * 0.5 + complexity * 0.3)
        return Forecast(
            cpu=min(1.0, cpu + complexity * 0.2), memory_mb=mem * steps,
            storage_mb=storage_mb, network=min(1.0, net), duration_s=round(duration, 3),
            automation_complexity=complexity, system_load=round(system_load, 4),
            confidence=0.65)

    def _current_load(self) -> float:
        if self._runtime is None:
            return 0.1
        try:
            health = self._runtime.health() if hasattr(self._runtime, "health") else {}
            return float(health.get("system_load", 0.1))
        except Exception:  # noqa: BLE001
            return 0.1


def _signature(action: str):
    a = (action or "").lower()
    for key, sig in _SIGNATURES.items():
        if key in a:
            return sig
    return _SIGNATURES["generic"]
