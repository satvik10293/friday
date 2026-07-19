"""
Small talk answered as herself, never parroted (M59.4).

Live-use bug: the owner said "hello" and she replied "hello friday, i am fine
friday" — she'd recalled past stored conversation turns and recited the
owner's OWN words back. Greetings / thanks / farewells / "how are you" now get
a direct reply BEFORE any retrieval, so nothing is parroted and no reasoner
(local or cloud) is consulted for a greeting.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.launcher.conversation import ConversationBridge, _SpeechOutput


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _IOS:
    """If this is ever consulted for small talk, that's the bug — it would
    retrieve + recite a stored turn."""
    def __init__(self):
        self.calls = 0

    def think(self, prompt, context=None, **kw):
        self.calls += 1
        return SimpleNamespace(task="general", strategy="ios", ok=True,
                               confidence=0.7, answer="hello friday i am fine friday",
                               models_used=[], structured={}, trace_id="t",
                               context_used={})


class _CloudSpy:
    def __init__(self):
        self.called = 0

    def available(self):
        return True

    def reason(self, q, *, context=None):
        self.called += 1
        return SimpleNamespace(ok=True, answer="essay", model="x", latency_ms=1.0)

    def status(self):
        return {}


def _bridge():
    ios = _IOS()
    cloud = _CloudSpy()
    bridge = ConversationBridge(
        ios, decision_log=_Log(), reasoner=cloud,
        speech=_SpeechOutput(synthesizer=lambda t: None))
    return bridge, ios, cloud


def test_hello_is_a_clean_greeting_not_a_parroted_turn():
    bridge, ios, cloud = _bridge()
    r = bridge.think("hello")
    assert "friday" not in r.answer.lower()      # never parrots her own name back
    assert "i am fine" not in r.answer.lower()   # never recites the owner's words
    assert ios.calls == 0 and cloud.called == 0  # no retrieval, no cloud
    assert bridge._decision_log.rows[-1]["route"] == ["smalltalk"]


def test_greeting_variants_all_handled_directly():
    for greet in ("hi", "hey friday", "hello friday", "yo", "good morning",
                  "what's up"):
        bridge, ios, cloud = _bridge()
        r = bridge.think(greet)
        assert r.answer and ios.calls == 0 and cloud.called == 0, greet


def test_how_are_you_is_smalltalk_not_system_status():
    bridge, ios, cloud = _bridge()
    r = bridge.think("how are you")
    assert "running well" in r.answer.lower()
    assert ios.calls == 0 and cloud.called == 0


def test_thanks_and_bye_are_direct():
    bridge, _, cloud = _bridge()
    assert bridge.think("thanks").answer == "Anytime."
    assert "talk soon" in bridge.think("bye").answer.lower()
    assert cloud.called == 0


def test_greeting_uses_the_owner_name_when_configured():
    bridge, _, _ = _bridge()
    bridge._owner_name = "Satvik"
    assert "Satvik" in bridge.think("hello").answer


def test_real_questions_are_not_swallowed_by_smalltalk():
    # a real question that merely starts like a greeting must still reason
    bridge, ios, cloud = _bridge()
    bridge.think("hey what is the capital of France")
    assert cloud.called == 1                      # went to the reasoner, not smalltalk


def test_a_long_utterance_is_not_smalltalk():
    bridge, ios, cloud = _bridge()
    bridge.think("hello can you please explain how photosynthesis works in detail")
    assert cloud.called == 1                       # too long/substantive for smalltalk
