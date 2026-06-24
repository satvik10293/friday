"""
tests/test_reasoner.py — FRIDAY 4.0 M5
Reasoner: memory contradiction detection, goal prioritization, dependency
reasoning, conflict reasoning, and integrated analyze() with confidence.
"""

import pytest

from core.context import ContextPackage
from core.executive import Reasoner, ReasoningResult
from core.goals import new_goal, GoalStatus


# ── memory reasoning ─────────────────────────────────────────────────────────
def test_detects_contradiction_same_topic():
    mems = [
        {"content": "The server is running", "topic": "server"},
        {"content": "The server is not running", "topic": "server"},
    ]
    out = Reasoner().reason_memory(mems)
    assert len(out) == 1 and "opposing" in out[0]["why"]


def test_no_contradiction_when_consistent():
    mems = [
        {"content": "The server is running", "topic": "server"},
        {"content": "The server is fast", "topic": "server"},
    ]
    assert Reasoner().reason_memory(mems) == []


# ── goal reasoning ───────────────────────────────────────────────────────────
def test_reason_goals_ranks_by_score():
    items = [
        {"target_id": "a", "label": "low", "score": 0.2},
        {"target_id": "b", "label": "high", "score": 0.9},
    ]
    ranked = Reasoner().reason_goals(items)
    assert [r["target_id"] for r in ranked] == ["b", "a"]


def test_reason_goals_derives_score_from_priority():
    items = [{"goal_id": "g1", "title": "t", "priority": 1}]
    ranked = Reasoner().reason_goals(items)
    assert ranked[0]["score"] > 0.9


# ── dependency reasoning ─────────────────────────────────────────────────────
def test_reason_dependencies_flags_unmet():
    dep = new_goal("Build Backend")           # PENDING
    g = new_goal("Build Frontend", dependencies=[dep.goal_id])
    missing = Reasoner().reason_dependencies([dep, g])
    assert any("waits on" in m for m in missing)


def test_reason_dependencies_satisfied_when_complete():
    dep = new_goal("Build Backend")
    dep.status = GoalStatus.COMPLETED
    g = new_goal("Build Frontend", dependencies=[dep.goal_id])
    assert Reasoner().reason_dependencies([dep, g]) == []


# ── conflict reasoning ───────────────────────────────────────────────────────
def test_reason_conflicts_detects_duplicate_active():
    a = new_goal("Deploy")
    b = new_goal("Deploy")
    a.status = b.status = GoalStatus.ACTIVE
    conflicts = Reasoner().reason_conflicts([a, b])
    assert len(conflicts) == 1


# ── integrated analyze ───────────────────────────────────────────────────────
def test_analyze_returns_reasoning_result():
    pkg = ContextPackage(query="q", memories=[{"content": "fact", "topic": "t"}],
                         focus_items=[{"target_id": "g1", "label": "Goal", "score": 0.8}],
                         confidence=0.6)
    res = Reasoner().analyze(pkg)
    assert isinstance(res, ReasoningResult)
    assert res.recommended_focus["target_id"] == "g1"
    assert res.considered >= 1


def test_analyze_confidence_penalized_by_gaps():
    pkg = ContextPackage(query="q", confidence=0.8)        # no memories, no goals
    res = Reasoner().analyze(pkg)
    assert res.missing_info                                 # gaps recorded
    assert res.confidence < 0.8


def test_analyze_flags_dependency_gaps_from_goals():
    dep = new_goal("dep")
    g = new_goal("main", dependencies=[dep.goal_id])
    pkg = ContextPackage(query="q", goals=[g.to_dict()])
    res = Reasoner().analyze(pkg, goals=[dep, g])
    assert any("waits on" in m for m in res.missing_info)
    assert Reasoner().health()["status"] == "ok"
