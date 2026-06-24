"""
core/attention/attention.py — FRIDAY 4.0 (M5)
The Attention System: decide what matters right now. It ranks goals, memories,
and observations by salience so the Executive Brain, Planner, and Context Engine
all focus on the same, defensible "most important things."

Stateless except for a metrics counter; the scoring math lives in scoring.py.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .scoring import (
    AttentionScore, DEFAULT_WEIGHTS, score_goal, score_memory, score_observation,
)

log = logging.getLogger("friday.attention")


class AttentionSystem:
    def __init__(self, weights: Optional[dict] = None) -> None:
        self._weights = weights or DEFAULT_WEIGHTS
        self._evaluations = 0

    # ── ranking ────────────────────────────────────────────────────────────────
    def rank_goals(self, goals: list, now: Optional[float] = None) -> list[AttentionScore]:
        now = now if now is not None else time.time()
        scored = [score_goal(g, now, self._weights) for g in goals]
        self._evaluations += len(scored)
        return self._sorted(scored)

    def rank_memories(self, memories: list[dict], now: Optional[float] = None) -> list[AttentionScore]:
        now = now if now is not None else time.time()
        scored = [score_memory(m, now, self._weights) for m in memories]
        self._evaluations += len(scored)
        return self._sorted(scored)

    def rank_observations(self, observations: list[dict],
                          now: Optional[float] = None) -> list[AttentionScore]:
        now = now if now is not None else time.time()
        scored = [score_observation(o, now, self._weights) for o in observations]
        self._evaluations += len(scored)
        return self._sorted(scored)

    def top(self, scores: list[AttentionScore], n: int = 5) -> list[AttentionScore]:
        return scores[:n]

    def focus(self, scores: list[AttentionScore]) -> Optional[AttentionScore]:
        """The single most salient item, or None if there's nothing to attend to."""
        return scores[0] if scores else None

    # ── diagnostics ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"evaluations": self._evaluations}

    def health(self) -> dict:
        return {"status": "ok", "evaluations": self._evaluations,
                "weights": dict(self._weights)}

    # ── internals ──────────────────────────────────────────────────────────────
    @staticmethod
    def _sorted(scores: list[AttentionScore]) -> list[AttentionScore]:
        return sorted(scores, key=lambda s: s.score, reverse=True)
