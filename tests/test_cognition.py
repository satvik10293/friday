"""
tests/test_cognition.py — FRIDAY 4.0 M5
Cognitive Loop: a single pass runs all ten phases; planning + (delegated) action
on active goals; idempotent start/stop; metrics; runtime scheduling; and safety
(run_cycle always returns — never an infinite loop).
"""

import time

import pytest

from core.cognition import CognitiveLoop, CognitivePhase, CognitionEvent
from core.executive import ExecutiveBrain


@pytest.fixture
def loop(memory_service, goal_service):
    brain = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service)
    return CognitiveLoop(brain, goal_service=goal_service, memory_service=memory_service)


# ── one pass ─────────────────────────────────────────────────────────────────
def test_run_cycle_executes_all_phases(loop):
    result = loop.run_cycle()
    assert result.phases == [p.value for p in CognitivePhase]   # all ten, in order
    assert result.reasoning is not None


def test_run_cycle_plans_over_active_goals(loop, goal_service):
    g = goal_service.create_goal("Do the work", priority=1)
    goal_service.activate_goal(g.goal_id)
    result = loop.run_cycle()
    assert result.plan_id is not None
    # the active, dependency-free goal is selected and acted on (synthetically)
    assert g.goal_id in result.actions


def test_run_cycle_stores_learning(loop, memory_service):
    loop.run_cycle(trigger="review architecture")
    hits = memory_service.recall("review architecture")
    assert any("Cognitive cycle" in h["content"] for h in hits)


def test_metrics_increment(loop):
    loop.run_cycle()
    loop.run_cycle()
    assert loop.metrics()["cognition_cycles"] == 2


def test_auto_execute_off_takes_no_action(memory_service, goal_service):
    brain = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service)
    passive = CognitiveLoop(brain, goal_service=goal_service,
                            memory_service=memory_service, auto_execute=False)
    g = goal_service.create_goal("X", priority=1)
    goal_service.activate_goal(g.goal_id)
    result = passive.run_cycle()
    assert result.actions == []


# ── lifecycle ────────────────────────────────────────────────────────────────
def test_start_stop_idempotent(loop):
    assert loop.start() is True
    assert loop.start() is False        # already running
    assert loop.running is True
    assert loop.stop() is True
    assert loop.stop() is False
    assert loop.running is False


def test_start_schedules_on_runtime(memory_service, goal_service, runtime):
    brain = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service,
                           runtime=runtime)
    cl = CognitiveLoop(brain, runtime=runtime, goal_service=goal_service,
                       memory_service=memory_service, interval_s=0.1)
    cl.start()
    # poll rather than a fixed sleep — a 0.1s interval can miss its first tick
    # under CPU contention, which made this test flaky in the full suite
    deadline = time.time() + 3.0
    while cl.metrics()["cognition_cycles"] < 1 and time.time() < deadline:
        time.sleep(0.05)
    cl.stop()
    assert cl.metrics()["cognition_cycles"] >= 1
    assert "cognition" in runtime.health()


def test_cycle_emits_event(memory_service, goal_service, runtime):
    brain = ExecutiveBrain(memory_service=memory_service, goal_service=goal_service,
                           runtime=runtime)
    cl = CognitiveLoop(brain, runtime=runtime, goal_service=goal_service,
                       memory_service=memory_service)
    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(CognitionEvent.CYCLE, _handler)
    cl.run_cycle()
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    assert seen, "expected a cognition.cycle event"


def test_status_shape(loop):
    loop.run_cycle()
    st = loop.status()
    assert st["cycles"] == 1 and st["last"] is not None
