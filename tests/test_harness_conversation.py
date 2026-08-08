"""
tests/test_harness_conversation.py — the harness wired into the live turn

Proves the ConversationBridge routes its cloud turn through the multi-provider
COUNCIL when one is configured, falls back to the single cloud reasoner when the
council can't answer, and degrades to the local team when neither is available —
all without a network (the harness is faked at the bridge boundary).
"""

from __future__ import annotations

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from tests.test_teacher import _Log, _LocalIOS


class _Result:
    def __init__(self, text, *, provider="openai", synthesized=True, council=None):
        self.text = text
        self.provider = provider
        self.confidence = 0.9
        self.latency_ms = 500.0
        self.meta = {"synthesized": synthesized,
                     "council": council or ["openai", "gemini", "groq"]}


class _Task:
    def __init__(self, result, *, succeeded=True):
        self.result = result
        self.succeeded = succeeded


class _FakeHarness:
    def __init__(self, task, *, available=True):
        self._task, self._available = task, available
        self.calls = []

    def has_available_provider(self, *a, **k):
        return self._available

    def run_auto_sync(self, command, context=None):
        self.calls.append((command, context))
        return self._task


class _FakeReasoner:
    def available(self):
        return True

    def reason(self, question, context=None):
        from core.intelligence.cloud_reasoner import ReasonedAnswer
        return ReasonedAnswer(ok=True, answer="single-reasoner answer",
                              model="groq-model", latency_ms=300.0)

    def status(self):
        return {"available": True}


def _bridge(ios, *, harness=None, reasoner=None):
    return ConversationBridge(ios, decision_log=_Log(), harness=harness,
                              reasoner=reasoner,
                              speech=_SpeechOutput(synthesizer=lambda t: None),
                              speak_answers=False)


def test_turn_routes_through_the_council():
    harness = _FakeHarness(_Task(_Result("Rayleigh scattering.")))
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ios, harness=harness)

    resp = bridge.think("explain why the sky is blue in detail")
    assert resp.answer == "Rayleigh scattering."
    assert resp.strategy == "harness_council"
    assert ios.thinks == 0                          # local team not consulted
    assert harness.calls and harness.calls[0][0].startswith("explain why")
    row = bridge._decision_log.rows[0]
    assert row["route"] == ["cloud_reasoner"]
    assert row["models_used"] == ["harness:openai", "harness:gemini", "harness:groq"]


def test_single_provider_answer_is_labelled_by_provider():
    harness = _FakeHarness(_Task(_Result("quick fact", provider="groq",
                                         synthesized=False, council=["groq"])))
    bridge = _bridge(_LocalIOS(confidence=0.9), harness=harness)
    resp = bridge.think("what is the capital of France")
    assert resp.answer == "quick fact"
    assert resp.strategy == "harness:groq"
    assert resp.models_used == ["harness:groq"]


def test_falls_back_to_single_reasoner_when_council_cannot_answer():
    harness = _FakeHarness(_Task(_Result(""), succeeded=False))
    bridge = _bridge(_LocalIOS(confidence=0.9), harness=harness,
                     reasoner=_FakeReasoner())
    resp = bridge.think("what is the capital of Australia")
    assert resp.answer == "single-reasoner answer"
    assert resp.strategy == "cloud_reasoner"


def test_degrades_to_local_when_no_cloud_available():
    harness = _FakeHarness(_Task(_Result("unused")), available=False)
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ios, harness=harness)          # no reasoner, council unavailable
    resp = bridge.think("what is the capital of Australia")
    assert ios.thinks == 1                          # local team answered
    assert resp.strategy == "chain_of_thought"
