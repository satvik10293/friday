"""
core/cognition_core/metrics.py — FRIDAY 6.0 (M13)
Lightweight metrics for the cognition core. Counters (resolutions by method, entities
created/merged, duplicate collisions, beliefs asserted/revised/retracted/conflicts)
plus a bounded latency window for belief updates. Published to Mission Control.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field


@dataclass
class CognitionMetrics:
    _counts: dict = field(default_factory=dict)
    _belief_latency_ms: deque = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def incr(self, key: str, by: int = 1) -> None:
        with self._lock:
            self._counts[key] = self._counts.get(key, 0) + by

    def record_belief_latency(self, ms: float) -> None:
        with self._lock:
            self._belief_latency_ms.append(float(ms))

    def get(self, key: str) -> int:
        return self._counts.get(key, 0)

    def snapshot(self) -> dict:
        with self._lock:
            counts = dict(self._counts)
            lat = list(self._belief_latency_ms)
        resolved = counts.get("resolved", 0) + counts.get("created", 0)
        collisions = counts.get("collision", 0)
        return {
            "resolutions": resolved,
            "entities_created": counts.get("created", 0),
            "entities_merged": counts.get("merged", 0),
            "duplicate_collisions": collisions,
            "duplicate_rate": round(collisions / resolved, 4) if resolved else 0.0,
            "by_method": {k.split(".", 1)[1]: v for k, v in counts.items()
                          if k.startswith("method.")},
            "beliefs_asserted": counts.get("belief.asserted", 0),
            "beliefs_revised": counts.get("belief.revised", 0),
            "beliefs_retracted": counts.get("belief.retracted", 0),
            "belief_conflicts": counts.get("belief.conflict", 0),
            "avg_belief_update_ms": round(sum(lat) / len(lat), 3) if lat else 0.0,
        }
