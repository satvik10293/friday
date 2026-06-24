"""
Tests for core/observability — tracing + the Decision Log.
Covers: trace identity/context, decision round-trip with JSON fields, the
"truthful independence" use case, durability/reopen, and stats.
"""

import pytest

from core.observability import (
    DecisionLog,
    start_trace,
    current_trace,
    get_trace_id,
    new_trace_id,
    clear_trace,
)


# ── tracing ────────────────────────────────────────────────────────────────────
def test_trace_ids_unique():
    assert new_trace_id() != new_trace_id()


def test_trace_context_roundtrip():
    t = start_trace("turn")
    try:
        assert current_trace() is t
        assert get_trace_id() == t.trace_id
        t.set(intent="chat", confidence=0.9)
        assert t.fields["intent"] == "chat"
        assert t.elapsed_ms() >= 0
    finally:
        clear_trace()
    assert current_trace() is None


# ── decision log ───────────────────────────────────────────────────────────────
def test_decision_roundtrip(tmp_path):
    dl = DecisionLog(path=tmp_path / "d.db")
    try:
        tid = new_trace_id()
        rid = dl.log(
            trace_id=tid,
            intent="question",
            route=["local"],
            models_used=["flan-t5-base"],
            skills_invoked=[],
            goals_touched=[],
            memory_used=[{"id": 1, "score": 0.82}],
            confidence=0.91,
            latency_ms=120,
            outcome="answered",
            rationale="local retrieval cleared the floor",
            was_autonomous=False,
            source="neural",
        )
        assert rid == 1

        rows = dl.by_trace(tid)
        assert len(rows) == 1
        r = rows[0]
        assert r["intent"] == "question"
        assert r["route"] == ["local"]               # JSON decoded back to a list
        assert r["memory_used"] == [{"id": 1, "score": 0.82}]
        assert r["was_autonomous"] is False
        assert r["confidence"] == 0.91
    finally:
        dl.close()


def test_truthful_independence_signal(tmp_path):
    """The Decision Log is what makes 'self vs API answered' a logged FACT,
    fixing the 3.0 hardcoded-True bug at the data layer."""
    dl = DecisionLog(path=tmp_path / "d.db")
    try:
        dl.log(intent="q", route=["local"], source="neural")    # answered locally
        dl.log(intent="q", route=["groq"], source="neural")     # needed the cloud
        dl.log(intent="q", route=["local"], source="neural")
        rows = dl.recent(limit=10)
        local = sum(1 for r in rows if "local" in r["route"])
        cloud = sum(1 for r in rows if "groq" in r["route"])
        assert local == 2 and cloud == 1
        independence = local / (local + cloud)
        assert abs(independence - (2 / 3)) < 1e-9
    finally:
        dl.close()


def test_decision_log_durable_reopen(tmp_path):
    p = tmp_path / "d.db"
    dl = DecisionLog(path=p)
    dl.log(trace_id="t", intent="x")
    dl.close()

    dl2 = DecisionLog(path=p)            # reopen: data survives
    try:
        assert dl2.stats()["total"] == 1
    finally:
        dl2.close()


def test_stats(tmp_path):
    dl = DecisionLog(path=tmp_path / "d.db")
    try:
        dl.log(intent="a", confidence=0.8, was_autonomous=True)
        dl.log(intent="b", confidence=0.6, was_autonomous=False)
        s = dl.stats()
        assert s["total"] == 2
        assert s["autonomous"] == 1
        assert abs(s["avg_confidence"] - 0.7) < 1e-9
    finally:
        dl.close()
