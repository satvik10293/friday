"""
M42 — the basic reasoner is the cloud (owner-directed).

Substantive, non-personal questions go to a frontier cloud model FIRST,
grounded in the conversation window plus privacy-filtered local memories.
Personal-shaped questions never leave the box. A cloud failure falls through
to the untouched local chain — and skips the teacher (same infrastructure).
Every cloud answer is truthful in the DecisionLog route ("cloud_reasoner")
and still flows through the learning gate.
"""

from __future__ import annotations

from core.intelligence.cloud_reasoner import CloudReasoner, ReasonedAnswer
from core.launcher.conversation import ConversationBridge, _SpeechOutput
from tests.test_teacher import _FakeTeacher, _LocalIOS, _Log, _Memory


# ── reasoner gating ───────────────────────────────────────────────────────────

def test_reasoner_is_unavailable_without_a_key():
    reasoner = CloudReasoner(primary="cloud", api_key="")
    assert reasoner.available() is False
    assert reasoner.reason("anything").ok is False


def test_reasoner_is_unavailable_when_primary_is_local():
    reasoner = CloudReasoner(primary="local", api_key="k")
    assert reasoner.available() is False


def test_reasoner_falls_through_its_model_chain():
    reasoner = CloudReasoner(primary="cloud", api_key="k",
                             model="broken-model",
                             fallback_models=["working-model"])
    calls = []

    def _call(model, messages):
        calls.append(model)
        if model == "broken-model":
            raise RuntimeError("503")
        return "Canberra."

    reasoner._call = _call
    answer = reasoner.reason("capital of Australia?")
    assert answer.ok and answer.model == "working-model"
    assert calls == ["broken-model", "working-model"]
    assert reasoner.stats.fallbacks == 1


def test_reasoner_never_raises_when_every_model_fails():
    reasoner = CloudReasoner(primary="cloud", api_key="k",
                             model="a", fallback_models=["b"])
    reasoner._call = lambda model, messages: (_ for _ in ()).throw(RuntimeError("down"))
    answer = reasoner.reason("anything")
    assert answer.ok is False and answer.error
    assert reasoner.stats.failed == 1


# ── bridge routing: cloud first, local fallback ───────────────────────────────

class _FakeReasoner:
    def __init__(self, ok=True):
        self.ok = ok
        self.asked = []
        self.contexts = []

    def available(self):
        return True

    def reason(self, question, context=None):
        self.asked.append(question)
        self.contexts.append(context)
        if self.ok:
            return ReasonedAnswer(ok=True, answer="Canberra is the capital.",
                                  model="gpt-oss-test", latency_ms=700.0)
        return ReasonedAnswer(ok=False, error="offline")

    def status(self):
        return {"primary": "cloud", "available": True}


def _bridge(ios, reasoner, teacher=None, memory=None):
    return ConversationBridge(ios, decision_log=_Log(), teacher=teacher,
                              memory=memory, reasoner=reasoner,
                              speech=_SpeechOutput(synthesizer=lambda t: None),
                              speak_answers=False)


def test_substantive_questions_ask_the_cloud_first():
    reasoner = _FakeReasoner()
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ios, reasoner)
    response = bridge.think("what is the capital of Australia?")
    assert response.answer == "Canberra is the capital."
    assert response.strategy == "cloud_reasoner"
    assert ios.thinks == 0, "local team consulted despite a cloud answer"
    row = bridge._decision_log.rows[0]
    assert row["route"] == ["cloud_reasoner"]
    assert row["models_used"] == ["groq:gpt-oss-test"]
    assert bridge.status()["cloud_turns"] == 1


def test_personal_questions_never_reach_the_cloud():
    reasoner = _FakeReasoner()
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ios, reasoner)
    bridge.think("what is my favorite color?")
    assert reasoner.asked == []
    assert ios.thinks == 1


def test_cloud_failure_falls_back_to_the_local_chain():
    reasoner = _FakeReasoner(ok=False)
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ios, reasoner)
    response = bridge.think("what is the capital of Australia?")
    assert ios.thinks == 1
    assert response.strategy == "chain_of_thought"
    assert "cloud_reasoner" not in bridge._decision_log.rows[0]["route"]


def test_teacher_is_skipped_when_the_cloud_already_failed_this_turn():
    reasoner = _FakeReasoner(ok=False)
    teacher = _FakeTeacher()
    bridge = _bridge(_LocalIOS(confidence=0.3), reasoner, teacher=teacher)
    bridge.think("what is the capital of France?")
    assert teacher.asked == [], \
        "teacher consulted after the cloud reasoner already timed out"


def test_no_reasoner_keeps_the_pre_m42_local_first_behaviour():
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(ios, reasoner=None)
    bridge.think("what is the capital of Australia?")
    assert ios.thinks == 1
    assert bridge.status()["reasoner"] == {"primary": "local"}


# ── grounding: window and privacy ─────────────────────────────────────────────

class _RecallMemory(_Memory):
    def recall(self, query, k=5):
        return [
            {"id": 1, "content": "my password is hunter2", "private": True},
            {"id": 2, "content": "FRIDAY runs on Windows", "private": False},
            {"id": 3, "content": "unknown provenance"},        # no flag → local
        ]


def test_private_memories_never_reach_the_cloud_reasoner():
    reasoner = _FakeReasoner()
    memory = _RecallMemory()
    bridge = _bridge(_LocalIOS(confidence=0.9), reasoner, memory=memory)
    bridge.think("what OS does FRIDAY use?")
    facts = reasoner.contexts[-1]["facts"]
    assert facts == ["FRIDAY runs on Windows"]
    # provenance: only the memories that were actually sent are recorded
    assert bridge._decision_log.rows[0]["memory_used"] == [2]


def test_the_cloud_reasoner_receives_the_conversation_window():
    reasoner = _FakeReasoner()
    bridge = _bridge(_LocalIOS(confidence=0.9), reasoner)
    bridge.think("who founded SpaceX?")
    bridge.think("how old is he?")
    turns = [t["text"] for t in reasoner.contexts[-1]["recent_turns"]]
    assert any("SpaceX" in t for t in turns)       # the anchor for "he"


def test_cloud_answers_flow_through_the_learning_gate():
    reasoner = _FakeReasoner()
    memory = _Memory()
    bridge = _bridge(_LocalIOS(confidence=0.9), reasoner, memory=memory)
    bridge.think("remember that the capital of Australia is Canberra")
    assert any("Canberra" in m for m in memory.remembered)
