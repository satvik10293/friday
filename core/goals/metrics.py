"""
core/goals/metrics.py — FRIDAY 4.0
Goal metrics: lightweight counters + a live snapshot over the store.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class GoalMetrics:
    created: int = 0
    activated: int = 0
    completed: int = 0
    failed: int = 0
    blocked: int = 0
    reflected: int = 0

    def snapshot(self, store=None) -> dict:
        d = asdict(self)
        if store is not None:
            d["by_status"] = store.counts_by_status()
        return d
