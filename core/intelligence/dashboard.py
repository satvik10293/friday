"""
core/intelligence/dashboard.py — FRIDAY 4.0 (M12)
Intelligence dashboard data (Part 16). Produces the live snapshot Mission Control
renders: loaded models, current routing/reasoning, agent activity, resources,
learning/reflection, confidence, benchmarks, and recent reasoning traces. Data-only
(no UI) — Mission Control mounts it as an "intelligence" panel.
"""

from __future__ import annotations



class IntelligenceDashboard:
    def __init__(self, ios) -> None:
        self._ios = ios

    def models_panel(self) -> dict:
        infos = self._ios.registry.infos()
        return {"count": len(infos),
                "loaded": [m["name"] for m in infos if m.get("status") == "loaded"],
                "models": [{"name": m["name"], "capabilities": m["capabilities"],
                            "accuracy": m["avg_accuracy"], "reliability": m["reliability"],
                            "speed_ms": m["avg_speed_ms"], "health": m["health"],
                            "benchmarks": m.get("benchmark_scores", {})} for m in infos]}

    def resources_panel(self) -> dict:
        return {"system": self._ios.monitor.system(),
                "memory_mb": self._ios.models.memory_usage_mb(),
                "cache": self._ios.cache.stats()}

    def traces_panel(self, limit: int = 10) -> dict:
        traces = self._ios.traces.recent(limit)
        return {"count": len(traces),
                "recent": [{"id": t["id"], "goal": t["goal"][:60], "task": t["task"],
                            "confidence": t["confidence"], "models": t["models"],
                            "ms": t["execution_ms"]} for t in traces]}

    def health_panel(self) -> dict:
        return self._ios.monitor.health()

    def snapshot(self) -> dict:
        return {
            "title": "Intelligence",
            "local_first": True,
            "models": self.models_panel(),
            "resources": self.resources_panel(),
            "traces": self.traces_panel(),
            "health": self.health_panel(),
            "registry": self._ios.registry.health(),
        }
