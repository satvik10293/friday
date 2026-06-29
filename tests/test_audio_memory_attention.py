"""M15 — Auditory Memory (meaningful-only persistence, session/sound retrieval,
chronicle forwarding) + Audio Attention (priority order, dynamic boost, M5 bridge)."""

import pytest

from core.audio.cognition.attention import AudioAttention
from core.audio.cognition.config import AttentionConfig
from core.audio.cognition.events import AuditoryEvent
from core.audio.cognition.memory import AuditoryMemory


def _event(sound="doorbell", conf=0.8, session="S1", category="alert"):
    return AuditoryEvent(sound=sound, category=category, confidence=conf, session_id=session)


# ── auditory memory ────────────────────────────────────────────────────────────────────
@pytest.fixture
def mem():
    m = AuditoryMemory(persistent=False, significance_threshold=0.6)
    try:
        yield m
    finally:
        m.close()


def test_only_meaningful_events_stored(mem):
    assert mem.remember(_event(conf=0.9)) is True
    assert mem.remember(_event(conf=0.3)) is False        # below threshold → dropped
    assert mem.counts()["events"] == 1


def test_emergency_significance_override(mem):
    # a low-confidence emergency can be forced significant by the caller
    assert mem.remember(_event(sound="glass_breaking", conf=0.4), significance=1.0) is True


def test_retrieval_by_sound_and_session(mem):
    mem.remember(_event(sound="doorbell", session="A"))
    mem.remember(_event(sound="alarm", conf=0.9, category="emergency", session="B"))
    assert len(mem.recent()) == 2
    assert len(mem.recent(sound="doorbell")) == 1
    assert len(mem.recent(session_id="B")) == 1
    assert mem.history("alarm")[0]["sound"] == "alarm"


def test_chronicle_forwarding():
    forwarded = []

    class Chronicle:
        def remember(self, text):
            forwarded.append(text)

    m = AuditoryMemory(persistent=False, significance_threshold=0.5, chronicle=Chronicle())
    m.remember(_event(sound="doorbell", conf=0.9))
    assert forwarded and "doorbell" in forwarded[0]
    m.close()


def test_memory_metrics(mem):
    mem.remember(_event(conf=0.9))
    assert mem.metrics()["writes"] == 1 and mem.health()["status"] == "ok"


# ── audio attention ────────────────────────────────────────────────────────────────────
def test_priority_order_matches_milestone():
    att = AudioAttention(AttentionConfig())
    signals = [
        {"kind": "background", "label": "hum"},
        {"kind": "environmental", "category": "alert", "label": "doorbell"},
        {"kind": "speech", "label": "command"},
        {"kind": "wake_word", "label": "friday"},
        {"kind": "emergency", "label": "glass"},
    ]
    order = [s["label"] for s in att.rank(signals)]
    assert order == ["glass", "friday", "command", "doorbell", "hum"]


def test_category_maps_to_band():
    att = AudioAttention(AttentionConfig())
    emergency = att.priority_for_signal(kind="", category="emergency")
    ambient = att.priority_for_signal(kind="", category="ambient")
    assert emergency > ambient


def test_dynamic_boost_and_decay():
    att = AudioAttention(AttentionConfig(dynamic=True))
    base = att.priority_for_signal(kind="environmental", now=0.0)
    att.note_activity("environmental", now=0.0)
    boosted = att.priority_for_signal(kind="environmental", now=0.0)
    assert boosted >= base
    decayed = att.priority_for_signal(kind="environmental", now=10.0)  # past 5 s decay
    assert decayed <= boosted


def test_static_when_dynamic_disabled():
    att = AudioAttention(AttentionConfig(dynamic=False))
    att.note_activity("environmental")
    assert att.priority_for_signal(kind="environmental") == att.priority_for_signal(
        kind="environmental")


def test_m5_attention_bridge():
    from core.attention.attention import AttentionSystem
    att = AudioAttention(AttentionConfig(), attention_system=AttentionSystem())
    scored = att.submit_to_attention([
        {"kind": "emergency", "label": "glass", "id": "e1"},
        {"kind": "background", "label": "hum", "id": "b1"}])
    # M5 returns AttentionScore objects ranked by salience; emergency outranks background
    assert scored and scored[0].label == "glass"
