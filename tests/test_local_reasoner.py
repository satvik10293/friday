"""
Her own local reasoning brain (M54).

The LocalReasoner is a real on-device model behind a scaffold WE own —
draft → self-critique → corrected final. These tests verify the scaffold and
the gating with a STUB backend (no multi-GB model download), plus that the
conversation bridge actually routes to the local brain when the cloud is off.
"""

from __future__ import annotations

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.intelligence.local_reasoner import LocalReasoner


class _StubBackend:
    """Records chat() calls and returns queued replies in order, so we can
    drive the draft → critique scaffold deterministically."""

    def __init__(self, replies, available=True):
        self._replies = list(replies)
        self._available = available
        self.calls = []

    def available(self):
        return self._available

    def chat(self, messages, *, max_tokens, temperature):
        self.calls.append({"messages": messages, "temperature": temperature})
        return self._replies.pop(0) if self._replies else ""


# ── the reasoning scaffold ────────────────────────────────────────────────────

def test_self_critique_corrects_the_draft():
    backend = _StubBackend(["2 + 2 = 5", "2 + 2 = 4"])   # draft, then correction
    r = LocalReasoner(backend=backend, self_check=True)
    ans = r.reason("what is 2 + 2?")
    assert ans.ok
    assert ans.answer == "2 + 2 = 4"                     # the corrected final
    assert len(backend.calls) == 2                       # draft + critique
    assert r.self_corrections == 1
    # the critique pass reasons at a lower temperature (faithful correction)
    assert backend.calls[1]["temperature"] <= backend.calls[0]["temperature"]


def test_self_check_keeps_a_correct_draft_verbatim():
    backend = _StubBackend(["the sky is blue", "the sky is blue"])
    r = LocalReasoner(backend=backend, self_check=True)
    ans = r.reason("why is the sky blue?")
    assert ans.answer == "the sky is blue"
    assert r.self_corrections == 0                        # nothing to correct


def test_self_check_off_uses_a_single_pass():
    backend = _StubBackend(["one-shot answer"])
    r = LocalReasoner(backend=backend, self_check=False)
    ans = r.reason("hi")
    assert ans.ok and ans.answer == "one-shot answer"
    assert len(backend.calls) == 1                        # no critique pass


def test_empty_draft_fails_so_the_caller_falls_through():
    backend = _StubBackend([""])                          # model produced nothing
    r = LocalReasoner(backend=backend, self_check=True)
    ans = r.reason("something")
    assert not ans.ok
    assert r.failed == 1


# ── availability gating (cheap + honest, no model load) ───────────────────────

def test_unavailable_backend_makes_the_brain_unavailable():
    r = LocalReasoner(backend=_StubBackend([], available=False))
    assert r.available() is False
    ans = r.reason("anything")
    assert not ans.ok and "unavailable" in ans.error


def test_disabled_config_disables_even_a_ready_backend():
    r = LocalReasoner(backend=_StubBackend(["x"], available=True), enabled=False)
    assert r.available() is False


# ── the bridge routes to the local brain when the cloud is off ────────────────

class _Response:
    def __init__(self, confidence=0.2, ok=True, answer="weak keyword answer"):
        self.task = "general"; self.strategy = "intelligence_os"; self.ok = ok
        self.answer = answer; self.confidence = confidence
        self.models_used = ["friday-reasoner"]; self.structured = {}
        self.trace_id = "t-1"; self.context_used = {}


class _IOS:
    def __init__(self):
        self.calls = []

    def think(self, prompt, context=None, **kw):
        self.calls.append(prompt)
        return _Response()


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


def test_bridge_routes_to_the_local_brain_before_the_keyword_team():
    spoken = []
    ios = _IOS()
    local = LocalReasoner(backend=_StubBackend(["a real reasoned answer",
                                                "a real reasoned answer"]))
    bridge = ConversationBridge(
        ios, decision_log=_Log(), local_reasoner=local,   # cloud reasoner=None
        speech=_SpeechOutput(synthesizer=spoken.append))
    resp = bridge.think("explain recursion")
    assert resp.answer == "a real reasoned answer"
    assert ios.calls == []                                 # keyword team skipped
    assert bridge.status()["local_turns"] == 1
    row = bridge._decision_log.rows[-1]
    assert "local_reasoner" in row["route"]
    assert spoken and spoken[-1] == "a real reasoned answer"


def test_bridge_falls_through_when_local_brain_is_unavailable():
    ios = _IOS()
    local = LocalReasoner(backend=_StubBackend([], available=False))
    bridge = ConversationBridge(
        ios, decision_log=_Log(), local_reasoner=local,
        speech=_SpeechOutput(synthesizer=lambda t: None))
    bridge.think("explain recursion")
    assert ios.calls and ios.calls[0] == "explain recursion"  # keyword team ran
    assert bridge.status()["local_turns"] == 0
