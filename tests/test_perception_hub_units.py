"""M17 — Perception Hub units: observation model, confidence engine, multimodal fusion,
context engine, timeline, cognitive reasoning."""

import time

import pytest

from core.perception.hub.config import (ConfidenceConfig, FusionConfig, TimelineConfig)
from core.perception.hub.confidence import ConfidenceEngine
from core.perception.hub.context import ContextEngine
from core.perception.hub.fusion import MultimodalFusion
from core.perception.hub.observations import ModalityObservation, UnifiedObservation
from core.perception.hub.reasoning import CognitiveReasoner
from core.perception.hub.timeline import Timeline


def _mo(source, category, label, conf=0.9, room="office", **data):
    return ModalityObservation(source=source, category=category, label=label,
                               confidence=conf, location=room,
                               objects=[label] if category == "object" else [], data=data)


# ── observation model ────────────────────────────────────────────────────────────────
def test_unified_observation_subject_signature():
    u = UnifiedObservation(event_category="user_state", location="kitchen",
                           related_objects=["bottle"], related_people=["user"],
                           audio_context={"sounds": ["running_water"]})
    assert "kitchen" in u.subject() and "bottle" in u.subject()
    assert "user" in u.signature() and "running_water" in u.signature()
    assert UnifiedObservation.__init__  # serializable
    import json
    json.dumps(u.to_dict())


def test_modality_observation_roundtrip():
    mo = _mo("vision", "object", "laptop")
    assert ModalityObservation.from_dict(mo.to_dict()).label == "laptop"


# ── confidence engine ────────────────────────────────────────────────────────────────
def test_confidence_noisy_or_raises_with_corroboration():
    eng = ConfidenceEngine(ConfidenceConfig())
    single = eng.combine([0.8])
    fused = eng.combine([0.8, 0.7])                    # independent corroboration
    assert fused > single and fused <= 1.0


def test_confidence_agreement_boost_and_conflict_penalty():
    eng = ConfidenceEngine(ConfidenceConfig(agreement_boost=0.1, conflict_penalty=0.3))
    agree = eng.combine([0.6, 0.6], agreement=True)
    conflict = eng.combine([0.6, 0.6], conflict=True)
    assert agree > conflict
    assert 0.0 <= conflict <= 1.0


def test_confidence_unify_detects_conflict():
    eng = ConfidenceEngine(ConfidenceConfig())
    obs = [_mo("spatial", "user_state", "present", user_state="present"),
           _mo("spatial", "user_state", "gone", user_state="unavailable")]
    res = eng.unify(obs)
    assert res["conflict"] is True


# ── fusion ───────────────────────────────────────────────────────────────────────────
def test_fusion_merges_modalities_by_location():
    f = MultimodalFusion(FusionConfig())
    unified = f.fuse([_mo("vision", "object", "bottle", room="kitchen"),
                      _mo("audio", "sound", "running_water", room="kitchen"),
                      _mo("vision", "object", "laptop", room="office")])
    by_loc = {u.location: u for u in unified}
    assert set(by_loc) == {"kitchen", "office"}
    k = by_loc["kitchen"]
    assert set(k.source_modules) == {"vision", "audio"}
    assert "bottle" in k.related_objects and "running_water" in k.audio_context["sounds"]


def test_fusion_confidence_combined():
    f = MultimodalFusion(FusionConfig())
    u = f.fuse([_mo("vision", "object", "x", conf=0.8, room="r"),
                _mo("audio", "sound", "y", conf=0.7, room="r")])[0]
    assert u.confidence > 0.8                          # corroboration raised certainty


# ── context engine ───────────────────────────────────────────────────────────────────
def test_context_updates_and_detects_change():
    ce = ContextEngine()
    u1 = UnifiedObservation(location="office", related_objects=["laptop"],
                            spatial_context={"user_state": "working"})
    r1 = ce.update(u1)
    assert r1["changed"] and ce.snapshot()["room"] == "office"
    u2 = UnifiedObservation(location="kitchen", related_objects=["bottle"])
    r2 = ce.update(u2)
    assert r2["changed"] and ce.previous()["room"] == "office"


def test_context_situation_change():
    ce = ContextEngine()
    u = UnifiedObservation(location="kitchen", conclusions=[{"situation": "preparing breakfast"}])
    r = ce.update(u)
    assert r["situation_changed"] and ce.snapshot()["situation"] == "preparing breakfast"


# ── timeline ─────────────────────────────────────────────────────────────────────────
def test_timeline_temporal_queries():
    tl = Timeline(TimelineConfig(capacity=100, recent_window_s=1000))
    now = time.time()
    for i in range(5):
        tl.add(UnifiedObservation(timestamp=now + i, event_category="object"))
    assert len(tl) == 5
    assert tl.current().timestamp == now + 4
    assert len(tl.before(now + 2)) == 2
    assert len(tl.after(now + 2)) == 2
    assert len(tl.during(now + 1, now + 3)) == 3
    assert len(tl.recently(seconds=1000)) == 5
    assert len(tl.by_category("object")) == 5


def test_timeline_bounded_capacity():
    tl = Timeline(TimelineConfig(capacity=10))
    for i in range(50):
        tl.add(UnifiedObservation(event_category="x"))
    assert len(tl) == 10                                # ring buffer bounds memory


# ── reasoning ────────────────────────────────────────────────────────────────────────
def test_reasoning_breakfast_rule():
    r = CognitiveReasoner()
    u = UnifiedObservation(location="kitchen", related_objects=["bottle"],
                           audio_context={"sounds": ["running_water"]}, confidence=0.9)
    c = r.reason(u, {})
    assert c and "breakfast" in c[0]["situation"].lower()


def test_reasoning_working_rule():
    r = CognitiveReasoner()
    u = UnifiedObservation(related_objects=["laptop", "keyboard"],
                           audio_context={"sounds": ["keyboard_typing"]}, confidence=0.9)
    c = r.reason(u, {})
    assert any("working" in x["situation"].lower() for x in c)


def test_reasoning_arrival_rule():
    r = CognitiveReasoner()
    u = UnifiedObservation(location="front door", audio_context={"sounds": ["doorbell"]},
                           confidence=0.9)
    c = r.reason(u, {})
    assert any("arrived" in x["situation"].lower() for x in c)


def test_reasoning_is_extensible():
    r = CognitiveReasoner()
    r.register_rule(lambda u, ctx: {"situation": "custom", "confidence": 1.0,
                                    "because": "x", "category": "test"}
                    if u.location == "lab" else None)
    c = r.reason(UnifiedObservation(location="lab", confidence=0.9), {})
    assert any(x["situation"] == "custom" for x in c)


def test_reasoning_bad_rule_isolated():
    r = CognitiveReasoner()
    r.register_rule(lambda u, ctx: 1 / 0)              # explodes
    c = r.reason(UnifiedObservation(location="kitchen", related_objects=["bottle"],
                                    audio_context={"sounds": ["running_water"]},
                                    confidence=0.9), {})
    assert c  # breakfast rule still fired despite the bad rule
