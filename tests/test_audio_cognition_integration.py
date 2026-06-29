"""M15 — Auditory Cognition integration: environmental sound → World Model (no bypass),
auditory memory, emergency → Executive + runtime events, speech dedup/wake via the
facade, M12.1 listening binding, manifest, side-effect-free import."""

import os
import tempfile

import numpy as np
import pytest

from core.audio.cognition import AudioCognitionConfig, AuditoryCognition
from core.world.world_model import WorldModel

SR = 16000


def tone(f, sec=0.6, amp=0.3):
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def noise(sec=0.6, amp=0.3, seed=1):
    return (amp * np.random.default_rng(seed).standard_normal(int(sec * SR))).astype(np.float32)


class FakeRuntime:
    def __init__(self):
        self.events = []

    def emit(self, signal, data=None, source=None):
        self.events.append((getattr(signal, "value", signal), data))

    def register_health(self, name, fn):
        self.health = (name, fn)

    def kinds(self):
        return [k for k, _ in self.events]


class StubExecutive:
    def __init__(self):
        self.alerts = []

    def on_audio_event(self, payload):
        self.alerts.append(payload)


def _cfg(**over):
    base = {"wake_word": "friday", "wake_confidence": 0.7, "store_audio_events": True,
            "memory": {"persistent": False, "significance_threshold": 0.5},
            "events": {"min_confidence": 0.45, "per_type_cooldown_s": 0.0}}
    base.update(over)
    return AudioCognitionConfig.from_dict(base)


@pytest.fixture
def world():
    wm = WorldModel(path=os.path.join(tempfile.mkdtemp(), "world.db"))
    try:
        yield wm
    finally:
        wm.close()


def test_environmental_sound_reaches_world_model(world):
    ac = AuditoryCognition(_cfg(), world_model=world)
    ev = ac.analyze_window(tone(700))
    assert ev is not None
    # the detected sound became a contextual observation written to the World Model
    kinds = {(e.kind, e.name) for e in world.all_entities()}
    assert any(k == "event" or n for (k, n) in kinds)
    assert ac.memory.counts()["events"] >= 1            # remembered (meaningful)
    ac.close()


def test_observation_routed_through_perception_no_bypass(world):
    # when a perception manager is injected, audio observations go through it (the
    # sanctioned path) rather than touching the World Model directly.
    ingested = []

    class StubPerception:
        def ingest(self, obs):
            ingested.append(obs)
            return {"status": "received", "significance": 0.8, "promoted": True}

    ac = AuditoryCognition(_cfg(), perception=StubPerception())
    ac.analyze_window(tone(700))
    assert ingested and ingested[0].type.value == "audio"
    assert ingested[0].metadata.get("entity_kind")
    ac.close()


def test_emergency_notifies_executive_and_runtime(world):
    rt, ex = FakeRuntime(), StubExecutive()
    ac = AuditoryCognition(_cfg(), world_model=world, runtime=rt, executive=ex)
    ac.analyze_window(noise(seed=3))                    # broadband → glass_breaking (emergency)
    assert ex.alerts and ex.alerts[0]["emergency"] is True
    assert "audio.emergency" in rt.kinds()
    assert "audio.sound.detected" in rt.kinds()
    ac.close()


def test_transcript_dedup_and_wake_via_facade(world):
    ac = AuditoryCognition(_cfg(), world_model=world)
    first = ac.on_transcript({"text": "friday what's the time", "confidence": 0.9})
    assert first["accepted"] and first["wake"] and first["command"] == "what's the time"
    dup = ac.on_transcript({"text": "friday what's the time", "confidence": 0.9})
    assert not dup["accepted"] and dup["reason"] == "duplicate"
    ac.close()


def test_self_speech_suppressed_via_facade(world):
    ac = AuditoryCognition(_cfg(), world_model=world)
    ac.speaking_started()
    res = ac.on_transcript({"text": "friday stop", "confidence": 0.9})
    assert res["suppressed"] is True
    ac.close()


def test_bind_listening_routes_transcripts():
    from core.audio.listener.events import AudioEvent
    from core.audio.listener.service import ListeningService
    ac = AuditoryCognition(_cfg())
    listening = ListeningService()
    ac.bind_listening(listening)
    # emitting a transcript on the listening bus should flow through dedup + wake
    listening.bus.emit(AudioEvent.TRANSCRIPT_READY,
                       {"text": "friday hello there", "confidence": 0.9})
    assert ac.wake.metrics()["activations"] == 1
    ac.close()


def test_dashboard_health_manifest():
    ac = AuditoryCognition(_cfg())
    d = ac.dashboard()
    assert d["title"] == "Auditory Cognition" and "engine" in d and "wake" in d
    assert ac.health()["status"] == "ok"
    m = ac.manifest()
    assert m["subsystem"] == "auditory_cognition" and m["milestone"] == "M15"
    ac.close()


def test_continuous_frame_processing():
    ac = AuditoryCognition(_cfg(events={"window_s": 0.4, "hop_s": 0.4,
                                        "min_confidence": 0.45, "per_type_cooldown_s": 0.0}))
    sig = tone(700, sec=1.2)
    fired = 0
    for i in range(0, sig.size, 320):
        if ac.process_frame(sig[i:i + 320]) is not None:
            fired += 1
    assert ac.engine.metrics()["windows"] >= 2          # continuous windowed analysis
    ac.close()


def test_config_from_flat_yaml_block():
    cfg = AudioCognitionConfig.from_dict({
        "wake_word": "athena", "continuous_listening": True, "wake_confidence": 0.9,
        "noise_filter": True, "audio_event_detection": True, "store_audio_events": False})
    assert cfg.wake.wake_word == "athena" and cfg.wake.wake_confidence == 0.9
    assert cfg.events.enabled is True and cfg.memory.store_audio_events is False


def test_side_effect_free_import():
    import importlib
    for mod in ("core.audio", "core.audio.cognition", "core.audio.cognition.service",
                "core.audio.cognition.engine", "core.audio.cognition.context"):
        importlib.import_module(mod)
