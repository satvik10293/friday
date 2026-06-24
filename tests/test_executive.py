"""
tests/test_executive.py — FRIDAY 4.0 M5
Executive Brain: think (context+reason+focus), decide (plan from goals), evaluate,
execute_plan (+ memory learning), observability, runtime events, health, and
cognitive-state recovery after restart.
"""

import time

import pytest

from core.executive import (
    ExecutiveBrain, ExecEvent, CognitiveStateStore, Plan, ReasoningResult,
)
from core.observability import DecisionLog


@pytest.fixture
def brain(tmp_path, memory_service, goal_service):
    dl = DecisionLog(tmp_path / "exec_dec.db")
    store = CognitiveStateStore(tmp_path / "exec_state.db")
    b = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service,
                       decision_log=dl, state_store=store)
    b._dl_path = tmp_path / "exec_dec.db"      # for assertions
    yield b
    store.close()
    dl.close()


# ── think ────────────────────────────────────────────────────────────────────
def test_think_returns_reasoning(brain, memory_service):
    memory_service.remember("user", "I want to build a dashboard")
    res = brain.think("what should I build?")
    assert isinstance(res, ReasoningResult)
    assert brain.metrics()["thoughts"] == 1


def test_think_sets_focus_from_active_goal(brain, goal_service):
    g = goal_service.create_goal("Important goal", priority=1)
    goal_service.activate_goal(g.goal_id)
    brain.think("focus")
    assert brain.state.current_focus is not None
    assert brain.state.current_focus.target_id == g.goal_id


# ── decide ───────────────────────────────────────────────────────────────────
def test_decide_builds_plan_from_goals(brain, goal_service):
    root = goal_service.plan("build a weather dashboard")   # root + 6 phases
    plan = brain.decide("build a weather dashboard")
    assert isinstance(plan, Plan)
    # one step per persisted goal (root + children)
    assert len(plan.steps) == len(goal_service.list_goals())
    assert brain.metrics()["plans_created"] == 1


def test_decide_without_goals_uses_scaffold(tmp_path, memory_service):
    b = ExecutiveBrain(memory_service=memory_service)       # no goal service
    plan = b.decide("write docs")
    assert len(plan.steps) == 3


# ── evaluate ─────────────────────────────────────────────────────────────────
def test_evaluate_reports_feasibility(brain, goal_service):
    g0 = goal_service.create_goal("Step A", priority=1)
    plan = brain.decide("do work")
    ev = brain.evaluate(plan)
    assert set(ev) >= {"feasible", "steps_total", "ready", "blocked", "confidence"}


# ── execute + learning ───────────────────────────────────────────────────────
def test_execute_plan_completes_and_learns(brain, memory_service):
    plan = brain.decide("tidy up")                          # scaffold (no skills)
    result = brain.execute_plan(plan)
    assert result.success
    hits = memory_service.recall("tidy up")
    assert any("Executed plan" in h["content"] for h in hits)
    assert brain.metrics()["plans_completed"] == 1


# ── observability ────────────────────────────────────────────────────────────
def test_decisions_logged(brain):
    brain.think("anything")
    rows = brain._decision.recent(10)
    assert any(r["intent"] == "executive.think" for r in rows)


def test_runtime_event_emitted(tmp_path, memory_service, goal_service, runtime):
    dl = DecisionLog(tmp_path / "ev_dec.db")
    b = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service,
                       decision_log=dl, runtime=runtime)
    b.attach(runtime)

    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(ExecEvent.PLAN_CREATED, _handler)
    b.decide("build something")

    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    assert seen, "expected an executive.plan_created event"
    dl.close()


def test_attach_registers_health(brain, runtime):
    brain.attach(runtime)
    health = runtime.health()
    assert "executive" in health and "context" in health and "attention" in health


def test_health_aggregates_subsystems(brain):
    h = brain.health()
    assert h["status"] == "ok"
    assert "context" in h and "attention" in h and "reasoner" in h


# ── recovery ─────────────────────────────────────────────────────────────────
def test_cognitive_state_survives_restart(tmp_path, memory_service, goal_service):
    state_db = tmp_path / "persist_state.db"
    store1 = CognitiveStateStore(state_db)
    b1 = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service,
                        state_store=store1)
    b1.decide("build the thing")
    assert b1.state.current_objective == "build the thing"
    store1.close()

    store2 = CognitiveStateStore(state_db)
    b2 = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service,
                        state_store=store2)
    assert b2.state.current_objective == "build the thing"
    assert b2.state.active_plan is not None
    store2.close()
