"""
core/brains/runtime/brain.py — FRIDAY V3 (M17 revision)
The Runtime Brain. Reports the health of FRIDAY's own machinery — event throughput,
service availability, and any degradation — so the Coordinator and Executive have a
situational picture of the system itself, not just the outside world. Reads only through
the RuntimeService (event history) and the service container's health.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class RuntimeBrain(CognitiveBrain):
    name = "runtime_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("event_rate", capacity=64)
        self._runtime = self._service("runtime")

    def observe(self):
        runtime = self._resolve("_runtime", "runtime")
        events = runtime.recent(limit=50) if runtime is not None else []
        health = {}
        if self.services is not None and hasattr(self.services, "health"):
            try:
                health = self.services.health()
            except Exception:  # noqa: BLE001
                health = {}
        return {"events": len(events), "health": health}

    def analyze(self, observation):
        services = observation.get("health", {}).get("services", {})
        degraded = [n for n, h in services.items()
                    if isinstance(h, dict) and h.get("status") in ("error", "degraded")]
        return {"event_count": observation["events"], "degraded": degraded,
                "status": observation.get("health", {}).get("status", "ok")}

    def update_local_memory(self, analysis) -> None:
        self.local.push("event_rate", analysis["event_count"])

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        # report only on CHANGE: first tick, a new/different degradation, or a
        # recovery — the old gate spammed the same degradation every tick and
        # never announced recovery
        degraded = sorted(insight["degraded"])
        previous = self.local.get("last_degraded")
        self.local.set("last_degraded", degraded)
        if self._ticks > 1 and degraded == previous:
            return None
        ok = not degraded
        recovered = ok and bool(previous)
        summary = ("All systems nominal again." if recovered else
                   "All systems nominal." if ok else
                   f"Degraded services: {', '.join(degraded)}.")
        return self._report(summary, confidence=0.9, priority=0.2 if ok else 0.8,
                            category="runtime", recommended_action=None if ok else "check_services",
                            data={"degraded": degraded, "status": insight["status"],
                                  "recovered": recovered})
