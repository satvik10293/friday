"""M14 — VisionSystem facade: full end-to-end perception, dashboard/health/manifest,
Mission Control panel, benchmark, singleton, side-effect-free import."""

import os
import tempfile

import numpy as np
import pytest

from core.attention.attention import AttentionSystem
from core.cognition_core.repositories import (InMemoryBeliefRepository,
                                              InMemoryEntityRepository)
from core.cognition_core.service import CognitionCore
from core.vision import VisionConfig, VisionSystem
from core.vision.mission_control import VisionPanel
from core.world.world_model import WorldModel


def _frames(n=6):
    out = []
    pos = [10, 60, 110]
    for i in range(n):
        img = np.full((120, 160, 3), 30, dtype=np.uint8)
        if i > 0:
            x = pos[i % 3]
            img[30:100, x:x + 50] = 200
        out.append(img)
    return out


@pytest.fixture
def system():
    cog = CognitionCore(entity_repository=InMemoryEntityRepository(),
                        belief_repository=InMemoryBeliefRepository())
    wm = WorldModel(path=os.path.join(tempfile.mkdtemp(), "world.db"))
    vs = VisionSystem(config=VisionConfig.from_dict({"memory": {"persistent": False}}),
                      cognition=cog, world_model=wm, attention=AttentionSystem())
    try:
        yield vs, cog, wm
    finally:
        vs.close()
        wm.close()


def test_end_to_end_perception(system):
    vs, cog, wm = system
    cid = vs.add_array_camera("cam", _frames(6), label="unit")
    results = [vs.process_camera(cid) for _ in range(6)]
    processed = [r for r in results if r.get("frame")]
    assert len(processed) == 6
    assert any(r["observations"] >= 1 for r in processed)
    assert any(r["events"] for r in processed)               # appeared/motion events fired
    assert cog.entities(), "vision created persistent entities through the resolver"
    assert vs.scene_graph.snapshot()["object_count"] >= 1
    assert vs.visual_memory.counts()["object_history"] >= 1


def test_processing_isolated_from_failures(system):
    vs, cog, wm = system
    cid = vs.add_array_camera("cam", _frames(2))
    # break a processor mid-flight; the system must isolate and keep going
    vs.pipeline._processors[0].analyze = lambda f: (_ for _ in ()).throw(RuntimeError("x"))
    r = vs.process_camera(cid)
    assert r.get("frame") is True                            # frame still processed, no crash
    assert vs.health()["status"] in ("ok", "degraded")


def test_dashboard_health_manifest(system):
    vs, cog, wm = system
    cid = vs.add_array_camera("cam", _frames(3))
    for _ in range(3):
        vs.process_camera(cid)
    d = vs.dashboard()
    assert d["title"] == "Vision System" and "transport" in d and "scene" in d
    assert vs.health()["status"] in ("ok", "degraded")
    m = vs.manifest()
    assert m["subsystem"] == "vision" and m["milestone"] == "M14"
    for stage in ("transport", "processing", "observation", "integration", "scene",
                  "memory", "service", "mission_control"):
        assert stage in m["stages"]


def test_mission_control_panel(system):
    vs, cog, wm = system
    cid = vs.add_array_camera("cam", _frames(3))
    for _ in range(3):
        vs.process_camera(cid)
    panel = VisionPanel(vs).panel()
    assert panel["camera_count"] == 1
    cam = panel["cameras"][0]
    for key in ("camera_id", "fps", "latency_ms", "queue_depth", "dropped", "health_score"):
        assert key in cam
    assert "object_count" in panel["perception"] and "detection_rate" in panel["perception"]
    assert "processing_thread_alive" in panel["threads"]


def test_mission_control_aggregator_includes_vision(system):
    vs, cog, wm = system
    from core.mission_control.aggregator import MissionControlAggregator
    agg = MissionControlAggregator(vision=vs)
    panels = agg.panels()
    assert "vision" in panels and panels["vision"]["status"] in ("ok", "degraded", "absent")
    # absent when no vision wired
    assert MissionControlAggregator().vision_panel()["status"] == "absent"


def test_benchmark_meets_targets():
    from core.vision.benchmark import run_benchmark
    rep = run_benchmark(frames=40)
    assert rep.detection_recall >= 0.9                       # motion reliably detected
    assert rep.observations_per_frame >= 1.0
    assert rep.pipeline_fps > 20                             # comfortably real-time on CPU
    import json
    json.dumps(rep.to_dict())


def test_singleton():
    from core.vision.service import get_vision_system
    a = get_vision_system(config=VisionConfig.from_dict({"memory": {"persistent": False}}))
    b = get_vision_system()
    assert a is b


def test_side_effect_free_import():
    import importlib
    for mod in ("core.vision", "core.vision.service", "core.vision.processing",
                "core.vision.observation", "core.vision.scene", "core.vision.memory",
                "core.vision.integration", "core.vision.mission_control"):
        importlib.import_module(mod)
