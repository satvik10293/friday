"""M17-rev — Cognitive Brain framework: situation reports, report bus, local memory,
lifecycle/tick never-raises, sensor brains, build_brains."""

import importlib

import pytest

from core.brains import (CognitiveBrain, LocalMemory, SituationReport, SituationReportBus,
                         build_brains)
from core.brains.audio.brain import AudioBrain
from core.brains.spatial.brain import SpatialBrain
from core.brains.vision.brain import VisionBrain
from core.services import ServiceName, build_default_container
from core.services.audio_service import AudioService
from core.services.vision_service import VisionService


# ── situation report + bus ──────────────────────────────────────────────────────────
def test_situation_report_to_dict():
    r = SituationReport(source_brain="vision_brain", summary="I see a cat", confidence=0.8,
                        priority=0.6, category="vision")
    d = r.to_dict()
    assert d["source_brain"] == "vision_brain" and d["summary"] == "I see a cat"
    assert d["report_id"].startswith("SR_")


def test_report_bus_publish_subscribe():
    bus = SituationReportBus()
    seen = []
    bus.subscribe(lambda r: seen.append(r.summary))
    bus.publish(SituationReport(source_brain="b", summary="hello"))
    assert seen == ["hello"] and bus.stats()["published"] == 1
    assert bus.recent()[0]["summary"] == "hello"


def test_report_bus_isolates_bad_subscriber():
    bus = SituationReportBus()
    bus.subscribe(lambda r: 1 / 0)
    bus.publish(SituationReport(source_brain="b", summary="x"))   # must not raise
    assert bus.stats()["published"] == 1


# ── local memory ────────────────────────────────────────────────────────────────────
def test_local_memory():
    lm = LocalMemory()
    lm.push("objects", "laptop", capacity=2)
    lm.push("objects", "phone")
    lm.push("objects", "cup")                          # evicts oldest (capacity 2)
    assert lm.items("objects") == ["phone", "cup"]
    lm.set("room", "office")
    assert lm.get("room") == "office"
    assert lm.summary()["caches"]["objects"] == 2


# ── lifecycle / never-raises ─────────────────────────────────────────────────────────
def test_brain_tick_never_raises():
    class Exploding(CognitiveBrain):
        name = "boom_brain"
        def observe(self): raise RuntimeError("kaboom")

    b = Exploding()
    assert b.tick() is None
    assert b.metrics()["errors"] == 1


def test_brain_publishes_report_on_tick():
    class Chatty(CognitiveBrain):
        name = "chatty"
        def generate_situation_report(self, insight):
            return self._report("something happened", category="test")

    bus = SituationReportBus()
    seen = []
    bus.subscribe(lambda r: seen.append(r))
    b = Chatty(report_bus=bus)
    r = b.tick()
    assert r is not None and seen and seen[0].source_brain == "chatty"


# ── sensor brains ────────────────────────────────────────────────────────────────────
def test_vision_brain_reports_objects():
    c = build_default_container()
    c.register(ServiceName.VISION, VisionService(provider=lambda: [
        {"object_class": "laptop", "label": "laptop", "confidence": 0.9},
        {"object_class": "person", "label": "person", "confidence": 0.92}]))
    b = VisionBrain(services=c)
    r = b.tick()
    assert r is not None and "object" in r.summary and r.data["people"] == 1
    assert "laptop" in b.local.items("object_cache")


def test_audio_brain_emergency_priority():
    c = build_default_container()
    c.register(ServiceName.AUDIO, AudioService(provider=lambda: [
        {"sound": "glass_breaking", "confidence": 0.9, "category": "emergency"}]))
    b = AudioBrain(services=c)
    r = b.tick()
    assert r is not None and r.category == "emergency" and r.priority >= 0.9
    assert r.recommended_action == "investigate"


def test_audio_brain_silent_no_report():
    c = build_default_container()
    c.register(ServiceName.AUDIO, AudioService(provider=lambda: []))
    assert AudioBrain(services=c).tick() is None


def test_spatial_brain_reports_user_state():
    c = build_default_container()

    class FakeSpatial:
        name = "spatial"
        def snapshot(self):
            return {"scene": {"objects": [{"label": "laptop"}], "rooms": [{"label": "office"}]},
                    "user": {"last_state": "working", "room": "office"}}
        def health(self): return {"status": "ok"}
    c.register(ServiceName.SPATIAL, FakeSpatial())
    r = SpatialBrain(services=c).tick()
    assert r is not None and "working" in r.summary and r.data["room"] == "office"


# ── society factory ──────────────────────────────────────────────────────────────────
def test_build_brains_society():
    c = build_default_container()
    bus = SituationReportBus()
    brains = build_brains(services=c, report_bus=bus)
    assert set(brains) >= {"vision_brain", "audio_brain", "spatial_brain", "memory_brain",
                           "learning_brain", "emotion_brain", "automation_brain", "runtime_brain"}
    assert c.get("memory_brain") is brains["memory_brain"]   # memory brain registered


def test_side_effect_free_import():
    import threading
    before = threading.active_count()
    importlib.import_module("core.brains")
    importlib.import_module("core.coordinator")
    assert threading.active_count() == before
