"""
tests/test_reflection.py — FRIDAY 4.0 M4
Reflection generation (lesson extraction) and its persistence into long-term
memory via the GoalService.
"""

import time

import pytest

from core.goals import (
    GoalService, GoalStore, GoalStatus, ReflectionEngine, new_goal,
)


@pytest.fixture
def store(tmp_path):
    s = GoalStore(path=tmp_path / "refl.db")
    try:
        yield s
    finally:
        s.close()


def _terminal_goal(store, status, **meta):
    g = new_goal("Integrate weather API")
    g.status = status
    g.metadata.update(meta)
    g.updated_at = g.created_at + 42.0
    store.create_goal(g)
    return g


def test_reflection_failed_maps_credential_lesson(store):
    g = _terminal_goal(store, GoalStatus.FAILED, failure_reason="missing api key")
    rec = ReflectionEngine(store).generate(g)
    assert rec.status == "failed"
    assert "credentials" in rec.lesson.lower()
    assert rec.duration_s == 42.0
    assert "missing api key" in rec.summary


def test_reflection_completed_summary(store):
    g = _terminal_goal(store, GoalStatus.COMPLETED)
    g.completion_percent = 100.0
    rec = ReflectionEngine(store).generate(g)
    assert rec.status == "completed"
    assert "repeat" in rec.lesson.lower()


def test_reflection_unknown_reason_falls_back(store):
    g = _terminal_goal(store, GoalStatus.FAILED, failure_reason="cosmic rays")
    rec = ReflectionEngine(store).generate(g)
    assert "cosmic rays" in rec.lesson


def test_reflection_records_skills(store):
    g = _terminal_goal(store, GoalStatus.COMPLETED, skills=["web.search", "fs.write"])
    rec = ReflectionEngine(store).generate(g)
    assert rec.skills_used == ["web.search", "fs.write"]


def test_service_reflect_persists_lesson_to_memory(store, memory_service):
    svc = GoalService(store=store, memory_service=memory_service)
    g = svc.create_goal("Integrate billing API")
    svc.fail_goal(g.goal_id, "unauthorized token")
    rec = svc.reflect(g.goal_id)
    assert rec is not None and "credentials" in rec.lesson.lower()

    hits = memory_service.recall("billing API lesson")
    assert any("Lesson" in h["content"] for h in hits)


def test_service_reflect_missing_goal_returns_none(store):
    svc = GoalService(store=store)
    assert svc.reflect("nope") is None


def test_reflect_logged_in_event_history(store, memory_service):
    svc = GoalService(store=store, memory_service=memory_service)
    g = svc.create_goal("Reflectable")
    svc.complete_goal(g.goal_id)
    svc.reflect(g.goal_id)
    kinds = [e["kind"] for e in store.get_events(g.goal_id)]
    assert "reflected" in kinds
