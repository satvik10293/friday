"""
core/society/reputation.py — FRIDAY 4.0 (M11)
Worker reputation. Every worker run updates its template's running scores —
accuracy, reliability, speed, resource efficiency, task success rate — combined
into a single 0..1 score. Top performers become *preferred templates* the
Coordinator reaches for first.
"""

from __future__ import annotations

import time
from typing import Optional

# Weights for the composite score.
_W = {"accuracy": 0.30, "reliability": 0.25, "success_rate": 0.20,
      "speed": 0.15, "efficiency": 0.10}


def _ewma(old: float, new: float, alpha: float = 0.3) -> float:
    return (1 - alpha) * old + alpha * new


class ReputationSystem:
    def __init__(self, store, *, preferred_threshold: float = 0.7) -> None:
        self._store = store
        self._threshold = preferred_threshold

    def record(self, template: str, *, success: bool, duration_ms: float,
               accuracy: float = 1.0, expected_ms: float = 200.0,
               cpu_ms: float = 0.0) -> dict:
        """Fold one worker run into the template's reputation."""
        rep = self._store.get_reputation(template) or {
            "template": template, "samples": 0, "accuracy": 0.0, "reliability": 0.0,
            "speed": 0.0, "efficiency": 0.0, "success_rate": 0.0, "score": 0.0,
            "updated_at": 0.0}
        n = rep["samples"]
        # speed: 1.0 if at/under expected, decaying as it overruns
        speed = max(0.0, min(1.0, expected_ms / max(1.0, duration_ms)))
        # efficiency: low CPU relative to wall time is efficient
        efficiency = max(0.0, min(1.0, 1.0 - (cpu_ms / max(1.0, duration_ms)))) if cpu_ms else 0.8
        succ = 1.0 if success else 0.0
        acc = accuracy if success else 0.0

        rep["accuracy"] = _ewma(rep["accuracy"], acc) if n else acc
        rep["reliability"] = _ewma(rep["reliability"], succ) if n else succ
        rep["success_rate"] = ((rep["success_rate"] * n) + succ) / (n + 1)
        rep["speed"] = _ewma(rep["speed"], speed) if n else speed
        rep["efficiency"] = _ewma(rep["efficiency"], efficiency) if n else efficiency
        rep["samples"] = n + 1
        rep["score"] = round(sum(_W[k] * rep[k] for k in _W), 4)
        rep["updated_at"] = time.time()
        self._store.save_reputation(rep)
        return rep

    def score(self, template: str) -> float:
        rep = self._store.get_reputation(template)
        return rep["score"] if rep else 0.0

    def get(self, template: str) -> Optional[dict]:
        return self._store.get_reputation(template)

    def is_preferred(self, template: str) -> bool:
        return self.score(template) >= self._threshold

    def top_templates(self, n: int = 5) -> list[dict]:
        return self._store.all_reputation()[:n]

    def preferred(self) -> list[str]:
        return [r["template"] for r in self._store.all_reputation()
                if r["score"] >= self._threshold]
