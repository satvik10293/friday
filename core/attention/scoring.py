"""
core/attention/scoring.py — FRIDAY 4.0 (M5)
Pure scoring functions for the attention system. Given importance, priority,
recency, and urgency, produce a single normalized salience score in [0, 1] plus
the component breakdown (so a decision is always explainable).

No I/O, no state — every function here is deterministic and unit-testable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Default weighting of the four salience components. Tunable; must sum to 1.0.
DEFAULT_WEIGHTS = {
    "importance": 0.35,
    "priority": 0.30,
    "recency": 0.20,
    "urgency": 0.15,
}


@dataclass
class AttentionScore:
    target_id: str
    kind: str                       # "goal" | "memory" | "observation"
    score: float
    components: dict = field(default_factory=dict)
    label: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def recency_score(ts: float, now: float | None = None, half_life_s: float = 3600.0) -> float:
    """1.0 for something just observed, decaying toward 0 with age. `half_life_s`
    is the age at which salience halves (default: 1 hour)."""
    now = now if now is not None else time.time()
    age = max(0.0, now - (ts or 0.0))
    return clamp01(half_life_s / (half_life_s + age))


def priority_score(priority: int) -> float:
    """Goal priority is 1 = highest. Map [1..10] → [1.0..0.0]."""
    return clamp01((10 - max(1, min(10, int(priority)))) / 9.0)


def combine(components: dict, weights: dict | None = None) -> float:
    w = weights or DEFAULT_WEIGHTS
    total = sum(w.get(k, 0.0) for k in components)
    if total <= 0:
        return 0.0
    return clamp01(sum(components.get(k, 0.0) * w.get(k, 0.0) for k in components) / total)


def score_memory(mem: dict, now: float | None = None, weights: dict | None = None) -> AttentionScore:
    comps = {
        "importance": clamp01(mem.get("importance", 0.5)),
        "priority": 0.5,                                    # memories have no priority
        "recency": recency_score(mem.get("ts", 0.0), now),
        "urgency": clamp01(mem.get("urgency", 0.3)),
    }
    return AttentionScore(
        target_id=str(mem.get("id", mem.get("content", "")))[:64],
        kind="memory", score=combine(comps, weights), components=comps,
        label=str(mem.get("content", ""))[:80],
    )


def score_goal(goal, now: float | None = None, weights: dict | None = None) -> AttentionScore:
    """`goal` is a core.goals.Goal (or any object exposing priority/updated_at/...)."""
    importance = clamp01(getattr(goal, "confidence", 0.5))
    comps = {
        "importance": importance,
        "priority": priority_score(getattr(goal, "priority", 5)),
        "recency": recency_score(getattr(goal, "updated_at", 0.0), now),
        "urgency": clamp01((goal.metadata or {}).get("urgency", 0.5)
                           if hasattr(goal, "metadata") else 0.5),
    }
    return AttentionScore(
        target_id=getattr(goal, "goal_id", ""), kind="goal",
        score=combine(comps, weights), components=comps,
        label=getattr(goal, "title", ""),
    )


def score_observation(obs: dict, now: float | None = None,
                      weights: dict | None = None) -> AttentionScore:
    comps = {
        "importance": clamp01(obs.get("importance", 0.5)),
        "priority": clamp01(obs.get("priority", 0.5)),
        "recency": recency_score(obs.get("ts", now or time.time()), now),
        "urgency": clamp01(obs.get("urgency", 0.5)),
    }
    return AttentionScore(
        target_id=str(obs.get("id", obs.get("name", "obs"))), kind="observation",
        score=combine(comps, weights), components=comps,
        label=str(obs.get("name", obs.get("label", "")))[:80],
    )
