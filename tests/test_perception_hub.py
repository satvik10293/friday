"""M17 — Perception Hub + service integration: multimodal fusion → unified observation,
World-Model gateway, memory dedup/compression, confidence rejection + enrichment,
events, perceive-from-services, executive understanding, never-raises, performance,
recovery, no circular imports, side-effect-free."""

import importlib
import os
import tempfile

import pytest

from core.perception.hub import (ModalityObservation, PerceptionHubConfig, PerceptionService)
from core.perception.hub.events import HubEvent
from core.services import ServiceName, build_default_container


class FakeRuntime:
    def __init__(self):
        self.events = []
    def emit(self, sig, data=None, source=None):
        self.events.append(getattr(sig, "value", sig))
    def register_health(self, n, p):
        pass


def _mo(source, category, label, conf=0.9, room="kitchen", **data):
    return ModalityObservation(source=source, category=category, label=label, confidence=conf,
                               location=room, objects=[label] if category == "object" else [],
                               data=data)


def _service(**over):
    cfg = {"minimum_confidence": 0.6}
    cfg.update(over)
    rt = FakeRuntime()
    container = build_default_container(runtime=rt)
    return PerceptionService(PerceptionHubConfig.from_dict(cfg), container=container), rt, container


def _breakfast():
    return [_mo("vision", "object", "bottle", room="kitchen"),
            _mo("audio", "sound", "running_water", conf=0.82, room="kitchen"),
            _mo("spatial", "user_state", "present", conf=0.96, room="kitchen", user_state="present")]


# ── fusion → unified → reasoning ─────────────────────────────────────────────────────
def test_multimodal_fusion_and_reasoning():
    svc, rt, _ = _service()
    r = svc.ingest(_breakfast())
    res = r["results"][0]
    assert res["accepted"] and set(svc.hub.timeline.current().source_modules) == {"vision", "audio", "spatial"}
    assert "breakfast" in res["conclusions"][0]["situation"].lower()
    assert svc.situation()["situation"].lower().find("breakfast") >= 0
    kinds = set(rt.events)
    assert HubEvent.OBSERVATION_MERGED.value in kinds
    assert HubEvent.REASONING_COMPLETED.value in kinds
    assert HubEvent.SITUATION_CHANGED.value in kinds
    assert HubEvent.PERCEPTION_READY.value in kinds
    svc.close()


def test_registers_into_container():
    svc, _, container = _service()
    assert container.get(ServiceName.PERCEPTION) is svc
    svc.close()


# ── World Model gateway ──────────────────────────────────────────────────────────────
def test_hub_is_world_model_gateway():
    from core.world.world_model import WorldModel
    wm = WorldModel(path=os.path.join(tempfile.mkdtemp(), "w.db"))
    svc = PerceptionService(PerceptionHubConfig.from_dict({"minimum_confidence": 0.6}),
                            container=build_default_container(world_model=wm))
    svc.ingest(_breakfast())
    sit = [e for e in wm.all_entities() if e.kind == "situation"]
    assert sit and sit[0].state.get("situation")
    svc.close(); wm.close()


# ── confidence rejection + enrichment ────────────────────────────────────────────────
def test_low_confidence_rejected():
    svc, rt, _ = _service(minimum_confidence=0.8)
    r = svc.ingest([_mo("vision", "object", "blob", conf=0.3, room="hall")])
    assert r["results"][0]["accepted"] is False
    assert HubEvent.OBSERVATION_REJECTED.value in set(rt.events)
    svc.close()


def test_borderline_enriched_from_context():
    svc, _, _ = _service(minimum_confidence=0.7)
    # establish context: office with a laptop
    svc.ingest([_mo("vision", "object", "laptop", conf=0.9, room="office"),
                _mo("audio", "sound", "keyboard_typing", conf=0.9, room="office")])
    # a borderline single-sensor obs in the same room with the same object gets enriched
    r = svc.ingest([_mo("vision", "object", "laptop", conf=0.55, room="office")])
    assert r["results"][0]["accepted"] is True         # enriched above threshold
    svc.close()


# ── memory dedup / compression ───────────────────────────────────────────────────────
def test_memory_compresses_repetitive_events():
    remembered = []

    class Mem:
        name = "memory"
        def remember(self, content, *, kind="event", metadata=None):
            remembered.append(content)
        def recall(self, q, *, limit=8): return []
        def health(self): return {"status": "ok"}

    container = build_default_container()
    container.register(ServiceName.MEMORY, Mem())
    svc = PerceptionService(PerceptionHubConfig.from_dict({"minimum_confidence": 0.6}),
                            container=container)
    for _ in range(5):                                 # identical breakfast situation ×5
        svc.ingest(_breakfast())
    assert len(remembered) == 1                         # compressed to a single memory
    svc.close()


# ── perceive from services ───────────────────────────────────────────────────────────
def test_perceive_pulls_from_services():
    container = build_default_container()
    from core.services.vision_service import VisionService
    from core.services.audio_service import AudioService
    container.register(ServiceName.VISION, VisionService(provider=lambda: [
        {"object_class": "bottle", "label": "bottle", "confidence": 0.9, "room": "kitchen"}]))
    container.register(ServiceName.AUDIO, AudioService(provider=lambda: [
        {"sound": "running_water", "confidence": 0.85, "category": "activity"}]))
    svc = PerceptionService(PerceptionHubConfig.from_dict({"minimum_confidence": 0.6}),
                            container=container)
    r = svc.perceive()
    assert r["observations"] >= 1
    svc.close()


# ── executive understanding ──────────────────────────────────────────────────────────
def test_provides_understanding_to_executive():
    notes = []

    class Exec:
        name = "executive"
        def notify(self, p): notes.append(p)
        def health(self): return {"status": "ok"}

    container = build_default_container()
    container.register(ServiceName.EXECUTIVE, Exec())
    svc = PerceptionService(PerceptionHubConfig.from_dict({"minimum_confidence": 0.6}),
                            container=container)
    svc.ingest(_breakfast())
    assert notes and notes[0]["type"] == "perception"
    assert "situation" in svc.situation()
    svc.close()


# ── resilience / config ──────────────────────────────────────────────────────────────
def test_never_raises_on_bad_service():
    class Exploding:
        name = "world_model"
        def observe(self, *a, **k): raise RuntimeError("boom")
        def relate(self, *a, **k): raise RuntimeError("boom")
        def get(self, e): raise RuntimeError("boom")
        def health(self): return {"status": "error"}
    container = build_default_container()
    container.register(ServiceName.WORLD_MODEL, Exploding())
    svc = PerceptionService(PerceptionHubConfig.from_dict({"minimum_confidence": 0.6}),
                            container=container)
    r = svc.ingest(_breakfast())
    assert "error" not in r and r["results"][0]["accepted"]   # world-model fault absorbed
    svc.close()


def test_disabled_is_noop():
    svc = PerceptionService(PerceptionHubConfig.from_dict({"enabled": False}),
                            container=build_default_container())
    assert svc.ingest(_breakfast()) == {"enabled": False}
    svc.close()


def test_fusion_disabled_wraps_each():
    svc = PerceptionService(PerceptionHubConfig.from_dict(
        {"fusion": False, "minimum_confidence": 0.0}), container=build_default_container())
    r = svc.ingest(_breakfast())
    assert r["observations"] == 3                       # one unified per modality
    svc.close()


# ── timeline scope queries ───────────────────────────────────────────────────────────
def test_timeline_scopes_via_service():
    svc, _, _ = _service()
    svc.ingest(_breakfast())
    assert svc.timeline(scope="recent")
    assert svc.timeline(scope="current")
    assert isinstance(svc.timeline(scope="historical"), list)
    svc.close()


# ── performance ──────────────────────────────────────────────────────────────────────
def test_handles_long_session():
    svc, _, _ = _service()
    for i in range(400):
        svc.ingest(_breakfast() if i % 2 else
                   [_mo("vision", "object", "laptop", room="office"),
                    _mo("audio", "sound", "keyboard_typing", room="office")])
    assert svc.hub.timeline.metrics()["size"] <= svc.config.timeline_cfg.capacity
    assert svc.metrics()["cycles"] == 400
    svc.close()


def test_benchmark_meets_targets():
    from core.perception.hub.benchmark import run_benchmark
    rep = run_benchmark(cycles=120)
    assert rep.cycles_per_s > 50
    assert rep.reasoning_rate > 0
    import json
    json.dumps(rep.to_dict())


# ── manifest / imports ───────────────────────────────────────────────────────────────
def test_manifest_and_dashboard():
    svc, _, _ = _service()
    m = svc.manifest()
    assert m["subsystem"] == "perception_hub" and m["milestone"] == "M17"
    assert svc.dashboard()["title"] == "Perception Hub"
    svc.close()


def test_no_circular_import():
    # the hub depends on services; services must NOT import the hub
    import ast, pathlib
    svc_imports = set()
    for p in pathlib.Path("core/services").rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                svc_imports.add(node.module)
    assert not [m for m in svc_imports if m and "perception.hub" in m]


def test_side_effect_free_import():
    for mod in ("core.perception.hub", "core.perception.hub.hub", "core.perception.hub.service",
                "core.perception.hub.fusion", "core.perception.hub.reasoning"):
        importlib.import_module(mod)
    # M6 perception package still imports fine (unchanged)
    importlib.import_module("core.perception")
