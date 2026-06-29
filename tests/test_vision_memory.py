"""M14 — Visual Memory: significant observations, visual events, object histories,
scene changes, retrieval, thresholding."""

import pytest

from core.perception.models import (ObservationSource, ObservationType, new_observation)
from core.vision.memory.visual_memory import VisualMemory


@pytest.fixture
def vm():
    m = VisualMemory(persistent=False, significance_threshold=0.5)
    try:
        yield m
    finally:
        m.close()


def _obs(name="laptop", conf=0.8, cam="CAM"):
    return new_observation(ObservationType.VISION, ObservationSource("vision", kind="camera"),
                           payload={"name": name}, confidence=conf,
                           metadata={"camera_id": cam, "subject": f"vision:obj:{cam}:{name}"})


def test_significance_threshold(vm):
    assert vm.remember_observation(_obs(), 0.9) is True
    assert vm.remember_observation(_obs(), 0.1) is False     # below threshold → not stored
    assert vm.counts()["observations"] == 1


def test_events_and_retrieval(vm):
    vm.record_event("CAM", "vision.motion.started", subject="s", data={"score": 0.2})
    vm.record_event("CAM2", "vision.scene.changed")
    assert len(vm.recent_events()) == 2
    assert len(vm.recent_events(camera_id="CAM")) == 1


def test_object_history_trim():
    m = VisualMemory(persistent=False, max_object_history=3)
    for i in range(6):
        m.record_sighting(stable_id="ENT_1", track_id="T1", camera_id="CAM",
                          label="laptop", center=(0.5, 0.5))
    hist = m.object_history("ENT_1")
    assert len(hist) == 3                                    # trimmed to max
    m.close()


def test_scene_changes(vm):
    vm.record_scene_change("CAM", 0.4, data={"object_count": 2})
    changes = vm.scene_changes("CAM")
    assert len(changes) == 1 and changes[0]["magnitude"] == 0.4


def test_recent_observations_order_and_filter(vm):
    vm.remember_observation(_obs(name="a", cam="CAM"), 0.9)
    vm.remember_observation(_obs(name="b", cam="OTHER"), 0.9)
    assert len(vm.recent_observations()) == 2
    assert len(vm.recent_observations(camera_id="CAM")) == 1
    assert vm.recent_observations()[0]["payload"]["payload"]["name"] in ("a", "b")


def test_health_and_metrics(vm):
    vm.remember_observation(_obs(), 0.9)
    assert vm.health()["status"] == "ok"
    assert vm.metrics()["writes"] >= 1
