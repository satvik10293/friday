"""
tests/test_environment_reasoning.py — FRIDAY 4.0 M6
PerceptiveBrain: observing the environment, summarizing it, and reasoning about
reality (world model + observations) rather than only memory.
"""

import pytest

from core.attention import AttentionSystem
from core.perception import (
    ObservationType, PerceptionManager, PerceptionStore, PerceptiveBrain, WorldFeed,
)
from core.sensors import Sensor, SensorManager
from core.world import WorldModel


class FakeSystemSensor(Sensor):
    name = "system"
    type = ObservationType.SYSTEM
    interval_s = 1.0

    def observe(self):
        return [self._obs({"cpu_pct": 95, "ram_pct": 80}, confidence=0.95,
                          metadata={"subject": "system:host", "impact": 0.9})]


@pytest.fixture
def stack(tmp_path, memory_service, goal_service):
    store = PerceptionStore(path=tmp_path / "p.db")
    wm = WorldModel(path=tmp_path / "w.db")
    att = AttentionSystem()
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm), attention=att,
                           goal_service=goal_service)
    sm = SensorManager(perception_manager=pm, store=store)
    sm.register(FakeSystemSensor())
    brain = PerceptiveBrain(world_model=wm, perception_manager=pm, sensor_manager=sm,
                            memory_service=memory_service, goal_service=goal_service)
    yield brain, pm, wm, sm
    store.close(); wm.close()


# ── observe ──────────────────────────────────────────────────────────────────
def test_observe_polls_and_ingests(stack):
    brain, pm, wm, sm = stack
    results = brain.observe()
    assert len(results) >= 1
    assert pm.stats()["ingested"] >= 1


def test_observe_promotes_to_world(stack):
    brain, pm, wm, sm = stack
    brain.observe()
    assert wm.counts()["entities"] >= 1        # high-impact system obs promoted


def test_observe_without_sensors_returns_empty(memory_service):
    brain = PerceptiveBrain(memory_service=memory_service)
    assert brain.observe() == []


# ── environment views ────────────────────────────────────────────────────────
def test_current_environment_groups_by_kind(stack):
    brain, pm, wm, sm = stack
    brain.observe()
    env = brain.current_environment()
    assert "system" in env
    assert env["system"][0]["state"]["cpu_pct"] == 95


def test_important_changes_ranked(stack):
    brain, pm, wm, sm = stack
    brain.observe()
    changes = brain.important_changes()
    assert isinstance(changes, list) and len(changes) >= 1


def test_important_changes_empty_without_perception(memory_service):
    brain = PerceptiveBrain(memory_service=memory_service)
    assert brain.important_changes() == []


# ── reasoning about reality ──────────────────────────────────────────────────
def test_analyze_environment_returns_reasoning(stack):
    brain, pm, wm, sm = stack
    brain.observe()
    report = brain.analyze_environment()
    assert set(report) >= {"environment", "important_changes", "reasoning", "summary"}
    assert "confidence" in report["reasoning"]


def test_analyze_environment_increments_reasoning(stack):
    brain, pm, wm, sm = stack
    before = brain.metrics()["reasoning_cycles"]
    brain.analyze_environment()
    assert brain.metrics()["reasoning_cycles"] == before + 1


# ── backward compatibility + health ──────────────────────────────────────────
def test_perceptive_brain_is_executive_brain(stack):
    from core.executive import ExecutiveBrain
    brain, pm, wm, sm = stack
    assert isinstance(brain, ExecutiveBrain)
    # inherited M5 behavior still works
    assert brain.think("anything") is not None
    assert len(brain.decide("build something").steps) >= 1


def test_health_includes_perception_and_sensors(stack):
    brain, pm, wm, sm = stack
    h = brain.health()
    assert "perception" in h and "sensors" in h
    assert h["status"] == "ok"
