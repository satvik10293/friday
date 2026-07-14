"""
core/brains/reasoning/brain.py — FRIDAY V3 (M46)
The Reasoning Brain. Watches FRIDAY's own thinking machinery — the local
Intelligence OS (model registry, cache) and the M42 cloud reasoner — and
reports its condition: "Reasoning: 6 local model(s), cloud reasoner healthy
(avg 1161 ms)." Degradation (cloud failures, models dropping) is reported at
raised priority with a recommendation; healthy steady state stays quiet.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport


class ReasoningBrain(CognitiveBrain):
    name = "reasoning_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.local.cache("latency_history", capacity=128)
        self._intelligence = self._service("intelligence")
        self._conversation = self._service("conversation")

    def observe(self):
        out: dict = {}
        ios = self._resolve("_intelligence", "intelligence")
        if ios is not None:
            try:
                out["health"] = ios.health_report() or {}
            except Exception:  # noqa: BLE001
                out["health"] = {}
        conversation = self._resolve("_conversation", "conversation")
        if conversation is not None:
            try:
                out["reasoner"] = (conversation.status() or {}).get("reasoner") or {}
            except Exception:  # noqa: BLE001
                out["reasoner"] = {}
        return out

    def analyze(self, observation):
        observation = observation or {}
        health = observation.get("health") or {}
        reasoner = observation.get("reasoner") or {}
        return {"models_loaded": int(health.get("models_loaded", 0) or 0),
                "cloud_available": bool(reasoner.get("available", False)),
                "cloud_model": str(reasoner.get("model", "") or ""),
                "cloud_failed": int(reasoner.get("failed", 0) or 0),
                "cloud_fallbacks": int(reasoner.get("fallbacks", 0) or 0),
                "avg_latency_ms": float(reasoner.get("avg_latency_ms", 0.0) or 0.0)}

    def update_local_memory(self, analysis) -> None:
        if analysis["avg_latency_ms"]:
            self.local.push("latency_history", analysis["avg_latency_ms"])

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        state = {"models": insight["models_loaded"],
                 "available": insight["cloud_available"],
                 "failed": insight["cloud_failed"],
                 "fallbacks": insight["cloud_fallbacks"]}
        previous = self.local.get("last_reasoning_state")
        self.local.set("last_reasoning_state", state)
        if state == previous:
            return None                              # steady state → no report
        degraded = (previous is not None and
                    (insight["cloud_failed"] > previous.get("failed", 0)
                     or insight["cloud_fallbacks"] > previous.get("fallbacks", 0)
                     or insight["models_loaded"] < previous.get("models", 0)))
        cloud = (f"cloud reasoner {insight['cloud_model'] or 'unconfigured'} "
                 + ("healthy" if insight["cloud_available"] and not degraded else
                    "degraded" if degraded else "offline"))
        latency = (f" (avg {insight['avg_latency_ms']:.0f} ms)"
                   if insight["avg_latency_ms"] else "")
        return self._report(
            f"Reasoning: {insight['models_loaded']} local model(s), {cloud}{latency}.",
            confidence=0.85, priority=0.7 if degraded else 0.3,
            category="reasoning",
            recommended_action="check_cloud_reasoner" if degraded else None,
            data=dict(insight, degraded=degraded))
