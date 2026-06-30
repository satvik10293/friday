"""
core/coordinator/config.py — FRIDAY V3 (M17 revision)
Configuration for the Cognitive Coordinator. Typed, serializable, injectable; no
hardcoded values. `from_dict` is tolerant (flat `coordinator:` block or nested).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class CoordinatorConfig:
    enabled: bool = True
    merge_window_s: float = 2.0             # reports within this window merge into one situation
    dedup_similarity: float = 0.92          # near-identical situations within the window are dropped
    dedup_window_s: float = 5.0
    min_priority_to_executive: float = 0.0  # gate trivial situations from the Executive
    timeline_capacity: int = 2000
    session_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "CoordinatorConfig":
        d = dict(d or {})
        if "coordinator" in d and isinstance(d["coordinator"], dict):
            d = d["coordinator"]
        cfg = CoordinatorConfig()
        for k in ("enabled", "merge_window_s", "dedup_similarity", "dedup_window_s",
                  "min_priority_to_executive", "timeline_capacity", "session_id"):
            if k in d:
                setattr(cfg, k, d[k])
        return cfg
