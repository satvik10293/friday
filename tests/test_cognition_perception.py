"""
tests/test_cognition_perception.py — FRIDAY 4.0 M6
PerceptiveCognitiveLoop: Observe + Fuse become first-class phases; sensors feed
the world model inside the cycle; planning/execution still work; events + metrics.
"""

import time

import pytest

from core.attention import AttentionSystem
from core.perception import (
    ObservationType, PERCEPTION_PHASES, PerceptionManager, PerceptionStore,
    PerceptiveBrain, PerceptiveCognitiveLoop, SensorFusion, WorldFeed,
)
from core.sensors import Sensor, SensorManager
from core.world import WorldModel


class FakeSystemSensor(Sensor):
    name = "system"
    type = ObservationType.SYSTEM
    interval_s = 1.0

    def observe(self):
        return [self._obs({"cpu_pct": 92}, confidence=0.95,
                          metadata={"subject": "system:host", "impact": 0.9})]


@pytest.fixture
def loop_stack(tmp_path, memory_service, goal_service):
    store = PerceptionStore(path=tmp_path / "p.db")
    wm = WorldModel(path=tmp_path / "w.db")
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm), attention=AttentionSystem(),
                           goal_service=goal_service)
    sm = SensorManager(perception_manager=pm, store=store)
    sm.register(FakeSystemSensor())
    brain = PerceptiveBrain(world_model=wm, perception_manager=pm, sensor_manager=sm,
                            memory_service=memory_service, goal_service=goal_service)

    def build(**kw):
        return PerceptiveCognitiveLoop(
            brain, sensor_manager=sm, perception_manager=pm, fusion=SensorFusion(),
            goal_service=goal_service, memory_service=memory_service, world_model=wm, **kw)

    yield build, brain, pm, wm, sm
    store.close(); wm.close()


# ── phases ───────────────────────────────────────────────────────────────────
def test_cycle_runs_all_eleven_phases(loop_stack):
    build, *_ = loop_stack
    result = build().run_cycle()
    assert result.phases == PERCEPTION_PHASES
    assert result.phases[:2] == ["observe", "fuse"]


def test_cycle_feeds_world_model(loop_stack):
    build, brain, pm, wm, sm = loop_stack
    build().run_cycle()
    assert wm.counts()["entities"] >= 1        # promoted system observation landed
    assert pm.stats()["ingested"] >= 1


# ── planning / execution ─────────────────────────────────────────────────────
def test_cycle_plans_and_acts_on_goals(loop_stack):
    build, brain, pm, wm, sm = loop_stack
    g = pm._goals.create_goal("Do the work", priority=1)
    pm._goals.activate_goal(g.goal_id)
    result = build().run_cycle()
    assert result.plan_id is not None
    assert g.goal_id in result.actions


def test_auto_execute_off_takes_no_action(loop_stack):
    build, *_ = loop_stack
    result = build(auto_execute=False).run_cycle()
    assert result.actions == []


# ── metrics / lifecycle ──────────────────────────────────────────────────────
def test_metrics_increment(loop_stack):
    build, *_ = loop_stack
    loop = build()
    loop.run_cycle()
    loop.run_cycle()
    assert loop.metrics()["cognition_cycles"] == 2


def test_start_stop_idempotent(loop_stack):
    build, *_ = loop_stack
    loop = build()
    assert loop.start() is True
    assert loop.start() is False
    assert loop.stop() is True
    assert loop.stop() is False


def test_learning_stored(loop_stack):
    build, brain, pm, wm, sm = loop_stack
    loop = build()
    loop.run_cycle(trigger="inspect environment")
    hits = brain._memory.recall("inspect environment")
    assert any("Cognitive cycle" in h["content"] for h in hits)


def test_status_shape(loop_stack):
    build, *_ = loop_stack
    loop = build()
    loop.run_cycle()
    st = loop.status()
    assert st["cycles"] == 1 and st["last"] is not None


# ── runtime event ────────────────────────────────────────────────────────────
def test_cycle_emits_event(loop_stack, runtime):
    build, brain, pm, wm, sm = loop_stack
    from core.cognition import CognitionEvent
    loop = build(runtime=runtime)
    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(CognitionEvent.CYCLE, _handler)
    loop.run_cycle()
    deadline = time.time() + 2.0
    while not seen and time.time() < deadline:
        time.sleep(0.02)
    assert seen, "expected a cognition.cycle event"
