"""
tests/test_attention.py — FRIDAY 4.0 M5
Attention scoring + ranking: component math, recency decay, priority mapping,
goal/memory ranking order, focus selection, metrics.
"""

import time

import pytest

from core.attention import (
    AttentionSystem, combine, priority_score, recency_score,
    score_goal, score_memory,
)
from core.goals import new_goal, GoalStatus


# ── scoring math ─────────────────────────────────────────────────────────────
def test_priority_score_monotonic():
    assert priority_score(1) > priority_score(5) > priority_score(10)
    assert priority_score(1) == pytest.approx(1.0)
    assert priority_score(10) == pytest.approx(0.0)


def test_recency_decay():
    now = time.time()
    fresh = recency_score(now, now)
    old = recency_score(now - 3600, now)        # one half-life old
    assert fresh > old
    assert old == pytest.approx(0.5, abs=0.01)


def test_combine_normalizes():
    comps = {"importance": 1.0, "priority": 1.0, "recency": 1.0, "urgency": 1.0}
    assert combine(comps) == pytest.approx(1.0)
    assert combine({}) == 0.0


def test_score_goal_components_present():
    g = new_goal("Important", priority=1, confidence=0.9)
    s = score_goal(g)
    assert s.kind == "goal" and 0.0 <= s.score <= 1.0
    assert set(s.components) == {"importance", "priority", "recency", "urgency"}


def test_score_memory_uses_importance():
    now = time.time()
    hi = score_memory({"id": 1, "content": "x", "importance": 0.9, "ts": now}, now)
    lo = score_memory({"id": 2, "content": "y", "importance": 0.1, "ts": now}, now)
    assert hi.score > lo.score


# ── ranking ──────────────────────────────────────────────────────────────────
def test_rank_goals_orders_by_salience():
    now = time.time()
    urgent = new_goal("urgent", priority=1, confidence=0.9)
    minor = new_goal("minor", priority=9, confidence=0.2)
    ranked = AttentionSystem().rank_goals([minor, urgent], now=now)
    assert ranked[0].target_id == urgent.goal_id


def test_rank_memories_orders_by_salience():
    now = time.time()
    mems = [
        {"id": 1, "content": "old trivia", "importance": 0.1, "ts": now - 7200},
        {"id": 2, "content": "fresh key fact", "importance": 0.9, "ts": now},
    ]
    ranked = AttentionSystem().rank_memories(mems, now=now)
    assert ranked[0].target_id == "2"


def test_focus_and_top():
    att = AttentionSystem()
    g1 = new_goal("a", priority=1)
    g2 = new_goal("b", priority=8)
    ranked = att.rank_goals([g2, g1])
    assert att.focus(ranked).target_id == g1.goal_id
    assert len(att.top(ranked, 1)) == 1


def test_metrics_and_health_track_evaluations():
    att = AttentionSystem()
    att.rank_goals([new_goal("a"), new_goal("b")])
    assert att.metrics()["evaluations"] == 2
    assert att.health()["status"] == "ok"


def test_empty_focus_is_none():
    assert AttentionSystem().focus([]) is None
