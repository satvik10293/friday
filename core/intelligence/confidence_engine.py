"""
core/intelligence/confidence_engine.py — FRIDAY 4.0 (M12)
Confidence estimation (Part 8). Every decision gets a 0–100% confidence derived from
knowledge quality, memory relevance, the number of agreeing models, past accuracy,
reasoning depth, and simulation support. Mission Control visualises it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_WEIGHTS = {
    "knowledge_quality": 0.22,
    "memory_relevance": 0.15,
    "model_agreement": 0.23,
    "past_accuracy": 0.20,
    "reasoning_depth": 0.10,
    "simulation_support": 0.10,
}


@dataclass
class ConfidenceBreakdown:
    score: float = 0.0
    signals: dict = field(default_factory=dict)

    @property
    def percent(self) -> int:
        return int(round(self.score * 100))

    def to_dict(self) -> dict:
        return {"score": round(self.score, 4), "percent": self.percent,
                "signals": self.signals}


class ConfidenceEngine:
    def estimate(self, *, context: Optional[dict] = None, agreement: float = 0.0,
                 past_accuracy: float = 0.5, reasoning_depth: int = 1,
                 simulation_support: float = 0.0) -> ConfidenceBreakdown:
        context = context or {}
        knowledge = context.get("knowledge", [])
        memories = context.get("memories", [])

        kq = (sum(float(k.get("confidence", 0.0)) for k in knowledge) / len(knowledge)
              if knowledge else 0.0)
        scores = [m["score"] for m in memories if m.get("score") is not None]
        mr = (sum(scores) / len(scores)) if scores else (0.4 if memories else 0.0)
        depth = max(0.0, min(1.0, reasoning_depth / 5.0))

        signals = {
            "knowledge_quality": round(kq, 4),
            "memory_relevance": round(mr, 4),
            "model_agreement": round(max(0.0, min(1.0, agreement)), 4),
            "past_accuracy": round(max(0.0, min(1.0, past_accuracy)), 4),
            "reasoning_depth": round(depth, 4),
            "simulation_support": round(max(0.0, min(1.0, simulation_support)), 4),
        }
        score = sum(_WEIGHTS[k] * v for k, v in signals.items())
        return ConfidenceBreakdown(score=round(max(0.0, min(1.0, score)), 4), signals=signals)
