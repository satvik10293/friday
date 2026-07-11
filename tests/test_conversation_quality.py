"""
Conversation quality — uncertainty handling and interruptible speech
(docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md §6 uncertainty, §8/barge-in).

FRIDAY is totally local — there is no cloud path:
· heard badly   → clarification, never a guess (and the local brain is not asked)
· thought badly → a second, deeper LOCAL reasoning pass, visible in the route
· barge-in      → speech stops mid-answer between sentences
"""

from __future__ import annotations

import threading
import time

from core.launcher.conversation import ConversationBridge, _SpeechOutput


class _Response:
    def __init__(self, confidence=0.8, ok=True, answer="local answer"):
        self.task = "general"
        self.strategy = "direct"
        self.ok = ok
        self.answer = answer
        self.confidence = confidence
        self.models_used = ["friday-reasoner"]
        self.structured = {}
        self.trace_id = "t-1"


class _IOS:
    """First pass returns `confidence`; a collaborate=True pass returns
    `deep_confidence`."""

    def __init__(self, confidence=0.8, deep_confidence=0.9, ok=True):
        self.calls = []
        self._confidence = confidence
        self._deep = deep_confidence
        self._ok = ok

    def think(self, prompt, context=None, collaborate=False, **kw):
        self.calls.append({"prompt": prompt, "collaborate": collaborate})
        if collaborate:
            return _Response(self._deep, self._ok, answer="deeper local answer")
        return _Response(self._confidence, self._ok)


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


def _bridge(ios=None, spoken=None):
    return ConversationBridge(
        ios if ios is not None else _IOS(), decision_log=_Log(),
        speech=_SpeechOutput(synthesizer=(spoken.append if spoken is not None
                                          else lambda t: None)))


# ── heard badly → clarify ─────────────────────────────────────────────────────

def test_low_audio_confidence_asks_for_clarification_instead_of_guessing():
    ios = _IOS()
    bridge = _bridge(ios=ios)
    response = bridge.think("mumble", context={"audio_confidence": 0.1})
    assert "say it again" in response.answer.lower()
    assert ios.calls == []                       # the brain was never asked to guess
    row = bridge._decision_log.rows[0]
    assert row["route"] == ["clarify"]
    assert bridge.status()["clarifications"] == 1


def test_clear_audio_is_not_clarified():
    ios = _IOS()
    bridge = _bridge(ios=ios)
    bridge.think("hello", context={"audio_confidence": 0.9})
    assert ios.calls and ios.calls[0]["prompt"] == "hello"


# ── thought badly → think harder, still locally ───────────────────────────────

def test_weak_answer_triggers_a_deeper_local_pass_visible_in_the_route():
    ios = _IOS(confidence=0.3, deep_confidence=0.7)
    bridge = _bridge(ios=ios)
    response = bridge.think("hard question")
    assert response.answer == "deeper local answer"
    assert [c["collaborate"] for c in ios.calls] == [False, True]
    row = bridge._decision_log.rows[0]
    assert "deep_reasoning" in row["route"]
    assert bridge.status()["escalations"] == 1


def test_confident_answer_never_triggers_a_second_pass():
    ios = _IOS(confidence=0.9)
    bridge = _bridge(ios=ios)
    response = bridge.think("easy question")
    assert response.answer == "local answer"
    assert len(ios.calls) == 1


def test_worse_deep_pass_keeps_the_first_answer():
    ios = _IOS(confidence=0.4, deep_confidence=0.2)
    bridge = _bridge(ios=ios)
    response = bridge.think("hard question")
    assert response.answer == "local answer"
    assert bridge.status()["escalations"] == 0


def test_deep_pass_failure_keeps_the_first_answer():
    class ExplodingDeepIOS(_IOS):
        def think(self, prompt, context=None, collaborate=False, **kw):
            if collaborate:
                raise RuntimeError("boom")
            return super().think(prompt, context, collaborate=False, **kw)

    bridge = _bridge(ios=ExplodingDeepIOS(confidence=0.3))
    response = bridge.think("hard question")
    assert response.answer == "local answer"
    assert response.ok


def test_deep_pass_reasons_over_the_same_retrieved_context():
    """The escalation pass must see the memories/knowledge the first pass
    retrieved — a deeper pass with LESS information is not deeper."""
    class ContextIOS(_IOS):
        def think(self, prompt, context=None, collaborate=False, **kw):
            self.calls.append({"prompt": prompt, "collaborate": collaborate,
                               "context": context})
            r = _Response(self._deep if collaborate else self._confidence,
                          self._ok,
                          answer="deeper local answer" if collaborate
                          else "local answer")
            if not collaborate:
                r.context_used = {"query": prompt,
                                  "memories": [{"id": 7, "content": "a fact",
                                                "score": 0.9}],
                                  "knowledge": [{"title": "t", "content": "k"}]}
            return r

    ios = ContextIOS(confidence=0.3, deep_confidence=0.7)
    bridge = _bridge(ios=ios)
    bridge.think("hard question")
    deep_call = ios.calls[1]
    assert deep_call["collaborate"]
    assert deep_call["context"]["memories"][0]["id"] == 7
    assert deep_call["context"]["knowledge"]


def test_memory_provenance_comes_from_the_reasoned_context():
    """DecisionLog memory_used lists the ids of the memories the models
    actually reasoned over — no separate (duplicate) retrieval."""
    class ContextIOS(_IOS):
        def think(self, prompt, context=None, collaborate=False, **kw):
            self.calls.append({"prompt": prompt, "collaborate": collaborate})
            r = _Response(0.9)
            r.context_used = {"memories": [{"id": 3, "content": "x", "score": 0.8},
                                           {"id": 5, "content": "y", "score": 0.7},
                                           {"content": "no id"}]}
            return r

    bridge = _bridge(ios=ContextIOS())
    bridge.think("what do you know")
    row = bridge._decision_log.rows[0]
    assert row["memory_used"] == [3, 5]


def test_nothing_in_the_bridge_references_a_cloud():
    import inspect

    import core.launcher.conversation as conversation
    source = inspect.getsource(conversation).lower()
    assert "import requests" not in source and "import urllib" not in source
    assert "api_key" not in source and "http" not in source


# ── speaking: interruptible ───────────────────────────────────────────────────

def test_speech_is_spoken_sentence_by_sentence_and_barge_in_stops_it():
    spoken, started = [], threading.Event()

    def slow_synth(sentence):
        spoken.append(sentence)
        started.set()
        time.sleep(0.15)

    speech = _SpeechOutput(synthesizer=slow_synth, stopper=lambda: None)
    speech.say("One. Two. Three. Four. Five.")
    assert started.wait(2.0)
    speech.interrupt()                    # barge-in after the first sentence(s)
    time.sleep(0.5)
    assert 0 < len(spoken) < 5            # stopped before finishing
    assert speech.interrupted == 1


def test_interrupt_drops_queued_utterances():
    gate = threading.Event()
    speech = _SpeechOutput(synthesizer=lambda s: gate.wait(1.0), stopper=lambda: None)
    speech.say("first utterance.")
    speech.say("second utterance.")
    speech.interrupt()
    gate.set()
    time.sleep(0.3)
    assert speech._queue.qsize() == 0


def test_bridge_interrupt_delegates_to_speech():
    bridge = _bridge()
    bridge.interrupt()
    assert bridge.status()["interrupted"] == 1
