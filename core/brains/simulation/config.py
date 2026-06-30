"""
core/brains/simulation/config.py — FRIDAY V3 (M19)
Configuration for the Simulation Brain. Typed, serializable, injectable; no hardcoded
values. Mirrors the milestone YAML:

    simulation:
      enabled: true
      max_scenarios: 5
      risk_threshold: 0.70
      timeout_seconds: 2
      cache_predictions: true
      learning_feedback: true
      store_successful_simulations: true

`from_dict` is tolerant (flat `simulation:` block or nested). Side-effect-free to import.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class SimulationConfig:
    enabled: bool = True
    max_scenarios: int = 5
    risk_threshold: float = 0.70           # plans above this risk are flagged/rejected
    timeout_seconds: float = 2.0
    cache_predictions: bool = True
    learning_feedback: bool = True
    store_successful_simulations: bool = True
    # ranking weights (decision evaluator) — configurable, not hardcoded
    weight_success: float = 0.45
    weight_risk: float = 0.35
    weight_time: float = 0.10
    weight_cost: float = 0.10
    history_capacity: int = 500

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: Optional[dict]) -> "SimulationConfig":
        d = dict(d or {})
        if "simulation" in d and isinstance(d["simulation"], dict):
            d = d["simulation"]
        cfg = SimulationConfig()
        for k in ("enabled", "max_scenarios", "risk_threshold", "timeout_seconds",
                  "cache_predictions", "learning_feedback", "store_successful_simulations",
                  "weight_success", "weight_risk", "weight_time", "weight_cost",
                  "history_capacity"):
            if k in d:
                setattr(cfg, k, d[k])
        return cfg
