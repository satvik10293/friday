"""M16 — Spatial engine + service integration: end-to-end scene updates, event bus,
World Model integration, recovery, vision-service poll, never-raises, performance,
config-driven behaviour, benchmark, manifest, side-effect-free import."""

import importlib
import os
import tempfile

import pytest

from core.services import ServiceContainer, ServiceName, build_default_container
from core.spatial import SpatialConfig, SpatialObservation, SpatialService
from core.spatial.events import SpatialEvent


def _obs(cls, x, y, w=0.08, h=0.08, room="office", conf=0.9):
    return SpatialObservation(object_class=cls, label=cls, confidence=conf,
                              bbox={"x": x, "y": y, "w": w, "h": h},
                              position={"x": x + w / 2, "y": y + h / 2},
                              camera_id="cam0", room=room)


class FakeRuntime:
    def __init__(self):
        self.events = []
    def emit(self, sig, data=None, source=None):
        self.events.append(getattr(sig, "value", sig))
    def register_health(self, n, p):
        self.health = (n, p)


def _service(**over):
    cfg = {"memory": {"persistent": False}}
    cfg.update(over)
    rt = FakeRuntime()
    container = build_default_container(runtime=rt)
    return SpatialService(SpatialConfig.from_dict(cfg), container=container), rt, container


# ── end-to-end ──────────────────────────────────────────────────────────────────────
def test_update_scene_builds_graph_and_publishes_events():
    svc, rt, _ = _service()
    s = svc.update_scene([_obs("desk", 0.2, 0.5, 0.5, 0.2), _obs("laptop", 0.3, 0.42, 0.15, 0.1),
                          _obs("person", 0.5, 0.75, 0.1, 0.2)], camera_id="cam0")
    assert s["detected"] == 3
    snap = svc.snapshot()
    assert snap["scene"]["node_count"] >= 4            # room + 3 objects
    kinds = set(rt.events)
    assert SpatialEvent.OBJECT_DETECTED.value in kinds
    assert SpatialEvent.SCENE_UPDATED.value in kinds
    assert SpatialEvent.USER_LOCATED.value in kinds
    svc.close()


def test_registers_itself_into_container():
    svc, _, container = _service()
    assert container.get(ServiceName.SPATIAL) is svc
    svc.close()


def test_world_model_updated_via_service():
    from core.world.world_model import WorldModel
    wm = WorldModel(path=os.path.join(tempfile.mkdtemp(), "w.db"))
    container = build_default_container(world_model=wm)
    svc = SpatialService(SpatialConfig.from_dict({"memory": {"persistent": False}}),
                         container=container)
    svc.update_scene([_obs("laptop", 0.3, 0.42), _obs("person", 0.5, 0.7)], camera_id="cam0")
    kinds = {(e.kind, e.name) for e in wm.all_entities()}
    assert ("user", "primary") in kinds                # user localized into the world model
    assert any(k == "object" for k, _ in kinds)        # object location written
    svc.close(); wm.close()


def test_query_through_service():
    svc, _, _ = _service()
    svc.update_scene([_obs("phone", 0.5, 0.5)], camera_id="cam0")
    assert svc.query("where_is", label="phone")["found"] is True
    assert svc.query("which_room", label="phone")["room"] == "office"
    svc.close()


# ── persistence / recovery ──────────────────────────────────────────────────────────
def test_scene_persistence_recovery(tmp_path):
    db = str(tmp_path / "spatial.db")
    cfg = SpatialConfig.from_dict({"memory": {"persistent": True, "db_path": db}})
    svc = SpatialService(cfg, container=build_default_container())
    svc.update_scene([_obs("laptop", 0.3, 0.42)], camera_id="cam0")
    svc.save()
    svc.close()
    # new service over same DB → load recovers the graph
    svc2 = SpatialService(SpatialConfig.from_dict({"memory": {"persistent": True, "db_path": db}}),
                          container=build_default_container())
    assert svc2.load() >= 2
    assert svc2.engine.scene.find("laptop")
    svc2.close()


# ── vision-service poll ─────────────────────────────────────────────────────────────
def test_poll_pulls_from_vision_service():
    detections = [{"object_class": "cup", "label": "cup", "confidence": 0.9,
                   "position": {"x": 0.5, "y": 0.5}, "camera_id": "cam0", "room": "kitchen"}]
    container = build_default_container()
    from core.services.vision_service import VisionService
    container.register(ServiceName.VISION, VisionService(provider=lambda: detections))
    svc = SpatialService(SpatialConfig.from_dict({"memory": {"persistent": False}}),
                         container=container)
    r = svc.poll(camera_id="cam0")
    assert r.get("detected") == 1 and svc.engine.scene.find("cup")
    svc.close()


# ── resilience ──────────────────────────────────────────────────────────────────────
def test_engine_never_raises_on_bad_service():
    class Exploding:
        name = "world_model"
        def observe(self, *a, **k): raise RuntimeError("boom")
        def relate(self, *a, **k): raise RuntimeError("boom")
        def get(self, e): raise RuntimeError("boom")
        def health(self): return {"status": "error"}
    container = build_default_container()
    container.register(ServiceName.WORLD_MODEL, Exploding())
    svc = SpatialService(SpatialConfig.from_dict({"memory": {"persistent": False}}),
                         container=container)
    s = svc.update_scene([_obs("phone", 0.5, 0.5)], camera_id="cam0")
    assert "error" not in s                             # spatial absorbed the world-model fault
    assert svc.health()["status"] == "ok"
    svc.close()


def test_disabled_is_noop():
    svc = SpatialService(SpatialConfig.from_dict({"enabled": False, "memory": {"persistent": False}}),
                         container=build_default_container())
    assert svc.update_scene([_obs("phone", 0.5, 0.5)]) == {"enabled": False}
    svc.close()


# ── performance (long session) ──────────────────────────────────────────────────────
def test_handles_long_session_with_pruning():
    svc, _, _ = _service()
    for t in range(300):                               # 300 updates × ~5 objects
        frame = [_obs(c, 0.1 + 0.1 * i + 0.0003 * t, 0.5)
                 for i, c in enumerate(["laptop", "keyboard", "mouse", "phone", "cup"])]
        svc.update_scene(frame, camera_id="cam0")
    # scene stays bounded (objects persist by identity; no unbounded growth)
    assert svc.engine.scene.counts()["objects"] <= 12
    assert svc.metrics()["updates"] == 300
    svc.close()


def test_benchmark_meets_targets():
    from core.spatial.benchmark import run_benchmark
    rep = run_benchmark(updates=120, n_objects=6)
    assert rep.updates_per_s > 50                      # comfortably real-time on CPU
    assert rep.tracked_objects >= 6
    import json
    json.dumps(rep.to_dict())


# ── manifest / imports ──────────────────────────────────────────────────────────────
def test_manifest_and_health():
    svc, _, _ = _service()
    m = svc.manifest()
    assert m["subsystem"] == "spatial" and m["milestone"] == "M16"
    assert svc.dashboard()["title"] == "Spatial Cognition"
    svc.close()


def test_side_effect_free_import():
    for mod in ("core.spatial", "core.spatial.engine", "core.spatial.service",
                "core.spatial.scene_graph", "core.spatial.tracker", "core.spatial.memory"):
        importlib.import_module(mod)


def test_no_circular_import_with_services():
    # spatial depends on services; services must NOT import spatial (one-way)
    import core.services, core.spatial  # noqa: F401
    import sys
    assert "core.spatial" not in _imports_of("core.services")


def _imports_of(pkg_name: str) -> set:
    import ast, pathlib
    root = pathlib.Path(pkg_name.replace(".", "/"))
    found = set()
    for p in root.rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    found.add(a.name)
    return found
