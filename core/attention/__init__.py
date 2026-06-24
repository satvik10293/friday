"""
core/attention — FRIDAY 4.0 (M5) Attention System.

Determines what matters right now by scoring goals, memories, and observations on
importance, priority, recency, and urgency. Import is side-effect free.

    from core.attention import AttentionSystem
    att = AttentionSystem()
    ranked = att.rank_goals(active_goals)
    focus = att.focus(ranked)        # the single most salient goal
"""

from .scoring import (
    AttentionScore, DEFAULT_WEIGHTS, combine, priority_score, recency_score,
    score_goal, score_memory, score_observation,
)
from .attention import AttentionSystem

__all__ = [
    "AttentionScore", "AttentionSystem", "DEFAULT_WEIGHTS",
    "combine", "priority_score", "recency_score",
    "score_goal", "score_memory", "score_observation",
]
