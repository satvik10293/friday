"""M12 — Confidence engine + critic engine."""

from core.intelligence.confidence_engine import ConfidenceEngine
from core.intelligence.critic import CriticEngine


# ── confidence ─────────────────────────────────────────────────────────────────────
def test_confidence_range():
    c = ConfidenceEngine().estimate()
    assert 0.0 <= c.score <= 1.0
    assert c.percent == int(round(c.score * 100))


def test_confidence_rises_with_evidence():
    eng = ConfidenceEngine()
    low = eng.estimate(context={"knowledge": [], "memories": []}, agreement=0.0)
    high = eng.estimate(
        context={"knowledge": [{"confidence": 0.9}], "memories": [{"score": 0.8}]},
        agreement=1.0, past_accuracy=0.9, reasoning_depth=5, simulation_support=1.0)
    assert high.score > low.score


def test_confidence_signals_present():
    c = ConfidenceEngine().estimate(agreement=0.5)
    assert set(c.signals) == {"knowledge_quality", "memory_relevance", "model_agreement",
                              "past_accuracy", "reasoning_depth", "simulation_support"}


def test_confidence_clamped():
    c = ConfidenceEngine().estimate(agreement=5.0, past_accuracy=5.0,
                                    reasoning_depth=100, simulation_support=5.0)
    assert c.score <= 1.0


# ── critic ─────────────────────────────────────────────────────────────────────────
def test_critic_flags_empty():
    r = CriticEngine().review("")
    assert not r.ok and any("empty" in i for i in r.issues)
    assert r.confidence_delta < 0


def test_critic_flags_missing_context():
    r = CriticEngine().review("A solid answer with substance.", context={})
    assert any("no supporting" in i for i in r.issues)


def test_critic_flags_hedging():
    r = CriticEngine().review("Maybe it works, perhaps, possibly, I think so.",
                              context={"knowledge": [{"x": 1}]})
    assert any("weak" in i or "hedged" in i for i in r.issues)


def test_critic_flags_overconfidence():
    r = CriticEngine().review("It is definitely X.", context={}, confidence=0.95)
    assert any("without supporting evidence" in i for i in r.issues)


def test_critic_passes_good_answer():
    r = CriticEngine().review(
        "Flask maps URLs to view functions using the route decorator, grounded in the docs.",
        structured={"steps": ["a", "b"]},
        context={"knowledge": [{"title": "Flask", "confidence": 0.9}]}, confidence=0.6)
    assert r.ok
    assert r.severity == "low"


def test_critic_report_serializable():
    import json
    json.dumps(CriticEngine().review("hi", context={}).to_dict())
