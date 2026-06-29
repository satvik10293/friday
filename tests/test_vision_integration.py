"""M14 — Cognitive Bridge integration: observations are routed through the existing
Attention → Perception → Entity Resolver → World Model path (never bypassing it), scene
objects are linked to permanent stable ids, and visual events fire. Vision performs no
reasoning."""

import os
import tempfile
import time

import numpy as np
import pytest

from core.attention.attention import AttentionSystem
from core.cognition_core.repositories import (InMemoryBeliefRepository,
                                              InMemoryEntityRepository)
from core.cognition_core.service import CognitionCore
from core.perception.manager import PerceptionManager
from core.vision.config import VisionConfig
from core.vision.integration.cognitive_bridge import CognitiveBridge
from core.vision.observation.builder import ObservationBuilder
from core.vision.processing.pipeline import VisionPipeline
from core.vision.processing.registry import default_registry
from core.vision.scene.scene_graph import SceneGraph
from core.vision.memory.visual_memory import VisualMemory
from core.world.world_model import WorldModel


@pytest.fixture
def stack():
    cog = CognitionCore(entity_repository=InMemoryEntityRepository(),
                        belief_repository=InMemoryBeliefRepository())
    wm = WorldModel(path=os.path.join(tempfile.mkdtemp(), "world.db"))
    perception = PerceptionManager(world_feed=cog.resolving_world_feed(wm),
                                   promote_confidence=0.5, promote_significance=0.3)
    sg = SceneGraph(VisionConfig().scene)
    vm = VisualMemory(persistent=False, significance_threshold=0.0)
    bridge = CognitiveBridge(perception=perception, cognition=cog,
                             attention=AttentionSystem(), scene_graph=sg,
                             visual_memory=vm, config=VisionConfig())
    try:
        yield cog, wm, perception, sg, vm, bridge
    finally:
        vm.close()
        wm.close()


def _pipe():
    cfg = VisionConfig().processing
    reg = default_registry(cfg)
    return VisionPipeline([reg.create(n) for n in ("scene_stats", "motion", "tracking")])


def _frame(square=None, n=1):
    from core.vision.transport.frame import frame_from_array
    img = np.full((120, 160, 3), 30, dtype=np.uint8)
    if square:
        x, y, w, h = square
        img[y:y + h, x:x + w] = 200
    return frame_from_array("CAMERA_0001", img, frame_number=n)


def test_observation_resolves_to_stable_id_no_bypass(stack):
    cog, wm, perception, sg, vm, bridge = stack
    pipe = _pipe()
    builder = ObservationBuilder(VisionConfig().observation)
    pipe.process(_frame(n=1))                                       # prime motion
    frame = _frame(square=(60, 40, 50, 50), n=2)
    result = pipe.process(frame)
    obs = builder.build(result, frame)
    out = bridge.process(result, obs, frame)

    # the object was resolved to a permanent stable id and linked into the scene graph
    assert out["linked"] >= 1
    assert any(sid.startswith("ENT_") for sid in out["stable_ids"].values())
    assert cog.entities(), "resolver created a persistent entity (no bypass)"
    linked = sg.objects("CAMERA_0001")
    assert linked and linked[0]["stable_id"].startswith("ENT_")


def test_object_appeared_and_motion_events(stack):
    cog, wm, perception, sg, vm, bridge = stack
    pipe = _pipe()
    builder = ObservationBuilder(VisionConfig().observation)
    pipe.process(_frame(n=1))
    frame = _frame(square=(60, 40, 50, 50), n=2)
    result = pipe.process(frame)
    out = bridge.process(result, builder.build(result, frame), frame)
    events = {e["event"] for e in out["events"]}
    assert "vision.object.appeared" in events
    assert "vision.motion.started" in events


def test_visual_memory_records_sightings_and_events(stack):
    cog, wm, perception, sg, vm, bridge = stack
    pipe = _pipe()
    builder = ObservationBuilder(VisionConfig().observation)
    pipe.process(_frame(n=1))
    frame = _frame(square=(60, 40, 50, 50), n=2)
    result = pipe.process(frame)
    bridge.process(result, builder.build(result, frame), frame)
    assert vm.counts()["object_history"] >= 1
    assert vm.counts()["events"] >= 1


def test_bridge_degrades_without_collaborators():
    # no perception/cognition/scene/memory → still safe, still updates nothing, no crash
    bridge = CognitiveBridge(config=VisionConfig())
    pipe = _pipe()
    builder = ObservationBuilder(VisionConfig().observation)
    frame = _frame(n=1)
    result = pipe.process(frame)
    out = bridge.process(result, builder.build(result, frame), frame)
    assert out["ingested"] >= 1 and out["linked"] == 0


def test_world_model_updated_on_promotion(stack):
    cog, wm, perception, sg, vm, bridge = stack
    pipe = _pipe()
    builder = ObservationBuilder(VisionConfig().observation)
    # repeat the same scene several times so perception promotes it to the world model
    for i in range(5):
        frame = _frame(square=(60, 40, 50, 50), n=i + 1)
        result = pipe.process(frame)
        bridge.process(result, builder.build(result, frame), frame)
    # the resolving world feed wrote at least one entity carrying a stable id
    ents = wm.all_entities()
    assert ents, "expected the world model to be updated via the resolving feed"
    assert any(e.attributes.get("stable_id", "").startswith("ENT_") for e in ents)
