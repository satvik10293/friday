"""
tests/test_context.py — FRIDAY 4.0 M5
Context Engine: assembling memories + goals + lessons + attention focus + world
into a ContextPackage, confidence scoring, and graceful degradation.
"""

import pytest

from core.attention import AttentionSystem
from core.context import ContextBuilder, ContextPackage
from core.world import WorldModel


def test_context_package_empty_and_summary():
    pkg = ContextPackage(query="q")
    assert pkg.is_empty
    assert "q" in pkg.summary()


def test_build_degrades_with_no_dependencies():
    pkg = ContextBuilder().build("anything")
    assert isinstance(pkg, ContextPackage)
    assert pkg.is_empty and pkg.confidence == 0.0


def test_build_pulls_memories(memory_service):
    memory_service.remember("user", "I am building the Friday assistant")
    builder = ContextBuilder(memory_service=memory_service)
    pkg = builder.build("what am I building?")
    assert any("Friday" in m["content"] for m in pkg.memories)
    assert pkg.confidence > 0.0


def test_build_includes_active_goals(goal_service, memory_service):
    g = goal_service.create_goal("Ship M5")
    goal_service.activate_goal(g.goal_id)
    builder = ContextBuilder(memory_service=memory_service, goal_service=goal_service,
                             attention=AttentionSystem())
    pkg = builder.build("what should I do?")
    titles = [g["title"] for g in pkg.goals]
    assert "Ship M5" in titles
    assert pkg.focus_items                      # attention ranked something


def test_build_collects_lessons(goal_service, memory_service):
    g = goal_service.create_goal("Integrate API")
    goal_service.fail_goal(g.goal_id, "missing api key")
    goal_service.reflect(g.goal_id)             # persists a reflection memory
    builder = ContextBuilder(memory_service=memory_service, goal_service=goal_service)
    pkg = builder.build("API integration")
    assert any("lesson" in str(l.get("content", "")).lower() or l.get("kind") == "reflection"
               for l in pkg.lessons)


def test_build_includes_world_summary(memory_service, tmp_path):
    wm = WorldModel(path=tmp_path / "ctx_world.db")
    wm.observe("project", "Friday", state={"phase": "M5"})
    builder = ContextBuilder(memory_service=memory_service, world_model=wm)
    pkg = builder.build("status")
    assert pkg.world.get("entities") == 1
    wm.close()


def test_builder_health_and_metrics(memory_service):
    builder = ContextBuilder(memory_service=memory_service)
    builder.build("x")
    assert builder.metrics()["builds"] == 1
    h = builder.health()
    assert h["memory"] is True and h["goals"] is False
