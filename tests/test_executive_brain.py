"""M17-rev / M18 foundation — Executive Brain: consumes only Unified Situations, refuses
raw data, focus by priority, decisions, Working-Memory-only, memory via the Memory Brain."""

import pytest

from core.brains.executive.brain import ExecutiveBrain
from core.services import ServiceName, build_default_container


def _situation(summary="user working", priority=0.5, category="user_state", **extra):
    return {"id": "US_1", "summary": summary, "priority": priority, "confidence": 0.8,
            "category": category, "source_brains": ["spatial_brain"], **extra}


# ── receive / refuse raw ─────────────────────────────────────────────────────────────
def test_receives_unified_situation():
    ex = ExecutiveBrain()
    res = ex.receive(_situation())
    assert res["accepted"] is True
    assert ex.working_memory.focus()["summary"] == "user working"


def test_refuses_raw_data():
    ex = ExecutiveBrain()
    for raw in ({"frame": b"x", "summary": "img"}, {"audio_samples": [1, 2], "summary": "snd"},
                {"detections": [], "summary": "d"}, {"scene_graph": {}, "summary": "s"}):
        res = ex.receive(raw)
        assert res["accepted"] is False and "raw" in res["reason"]
    assert ex.status()["refused_raw"] == 4


def test_focus_tracks_highest_priority():
    ex = ExecutiveBrain()
    ex.receive(_situation("low", priority=0.3))
    ex.receive(_situation("urgent", priority=0.9, category="emergency"))
    ex.receive(_situation("medium", priority=0.5))
    assert ex.working_memory.focus()["summary"] == "urgent"


# ── decisions ────────────────────────────────────────────────────────────────────────
def test_decide_on_focus():
    ex = ExecutiveBrain()
    ex.receive(_situation("Glass breaking!", priority=1.0, category="emergency",
                          recommended_action="alert_user"))
    decision = ex.decide()
    assert decision["decision"] == "alert_user"


def test_decide_idle_without_situation():
    ex = ExecutiveBrain()
    assert ex.decide()["decision"] == "idle"


def test_decide_delegates_to_planner():
    class Planner:
        def decide(self, objective):
            return {"objective": objective, "steps": ["a", "b"]}
    ex = ExecutiveBrain(planner=Planner())
    d = ex.decide("ship the release")
    assert d["source"] == "planner" and d["objective"] == "ship the release"


# ── memory only via the Memory Brain ─────────────────────────────────────────────────
def test_request_memory_goes_through_memory_brain():
    class MemBrain:
        name = "memory_brain"
        def recall(self, query, *, limit=5): return [{"content": f"recalled {query}"}]
    c = build_default_container()
    c.register("memory_brain", MemBrain())
    ex = ExecutiveBrain(services=c)
    hits = ex.request_memory("phone")
    assert hits and "phone" in hits[0]["content"]


def test_request_memory_empty_without_memory_brain():
    assert ExecutiveBrain().request_memory("x") == []


# ── resilience ───────────────────────────────────────────────────────────────────────
def test_decide_survives_planner_failure():
    class BadPlanner:
        def decide(self, objective): raise RuntimeError("planner down")
    ex = ExecutiveBrain(planner=BadPlanner())
    ex.receive(_situation("fallback situation", priority=0.6))
    d = ex.decide("do something")
    assert "decision" in d                              # fell back to focus-based decision


def test_health_and_metrics():
    ex = ExecutiveBrain()
    ex.receive(_situation())
    assert ex.health()["status"] == "ok"
    assert ex.metrics()["received"] == 1
