"""
M30 — the temporary teacher (Groq as scaffolding, not brain).

FRIDAY consults a cloud teacher ONLY when both local passes stay weak; the
teacher's answer replaces hers for that turn, is visible in the DecisionLog
route ("groq_teacher"), and is learned back into memory so the next similar
question is answered locally. No key / disabled / teacher failure → her honest
local answer stands. Strong local answers never reach the teacher.
"""

from __future__ import annotations

from core.intelligence.teacher import GroqTeacher, TeacherAnswer
from core.launcher.conversation import ConversationBridge, _SpeechOutput


# ── teacher gating ────────────────────────────────────────────────────────────

def test_teacher_is_unavailable_without_a_key():
    teacher = GroqTeacher(enabled=True, api_key="")
    assert teacher.available() is False
    assert teacher.ask("anything").ok is False


def test_teacher_is_unavailable_when_disabled():
    teacher = GroqTeacher(enabled=False, api_key="k")
    assert teacher.available() is False


# ── bridge escalation ─────────────────────────────────────────────────────────

class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _LocalIOS:
    """Local team with a fixed confidence."""

    def __init__(self, confidence):
        self.confidence = confidence
        self.thinks = 0

    def think(self, command, context=None, **kw):
        self.thinks += 1

        class _R:
            ok = True
            task = "general"
            strategy = "chain_of_thought"
            models_used = ["friday-reasoner"]
            trace_id = None
            answer = "I don't know enough about that yet."
        _R.confidence = self.confidence
        return _R()


class _FakeTeacher:
    def __init__(self, ok=True):
        self.ok = ok
        self.asked = []

    def available(self):
        return True

    def ask(self, question):
        self.asked.append(question)
        if self.ok:
            return TeacherAnswer(ok=True, answer="Paris is the capital of France.",
                                 model="llama-test", latency_ms=42.0)
        return TeacherAnswer(ok=False, error="down")

    def status(self):
        return {"enabled": True, "available": True}


class _Memory:
    def __init__(self):
        self.remembered = []

    def recall(self, query, k=5):
        return []

    def remember(self, who, content, **kw):
        self.remembered.append(content)
        return len(self.remembered)


def _bridge(ios, teacher, memory=None):
    return ConversationBridge(ios, decision_log=_Log(), teacher=teacher,
                              memory=memory,
                              speech=_SpeechOutput(synthesizer=lambda t: None),
                              speak_answers=False)


def test_weak_local_answer_escalates_to_the_teacher_and_is_learned():
    teacher = _FakeTeacher()
    memory = _Memory()
    bridge = _bridge(_LocalIOS(confidence=0.3), teacher, memory)
    response = bridge.think("what is the capital of France?")
    assert response.answer == "Paris is the capital of France."
    assert response.confidence == 0.85
    assert teacher.asked == ["what is the capital of France?"]
    row = bridge._decision_log.rows[0]
    assert row["route"][-1] == "groq_teacher"          # truthful independence
    assert row["models_used"] == ["groq:llama-test"]
    # the taught answer went through the learning gate into memory
    assert any("Paris" in m for m in memory.remembered)
    assert bridge.status()["teacher_turns"] == 1


def test_confident_local_answers_never_reach_the_teacher():
    teacher = _FakeTeacher()
    bridge = _bridge(_LocalIOS(confidence=0.9), teacher)
    response = bridge.think("what is two plus two?")
    assert teacher.asked == []
    assert "groq_teacher" not in bridge._decision_log.rows[0]["route"]
    assert response.confidence == 0.9


def test_teacher_failure_leaves_the_honest_local_answer():
    teacher = _FakeTeacher(ok=False)
    bridge = _bridge(_LocalIOS(confidence=0.3), teacher)
    response = bridge.think("what is the capital of France?")
    assert "don't know enough" in response.answer
    assert "groq_teacher" not in bridge._decision_log.rows[0]["route"]


def test_no_teacher_means_fully_local():
    bridge = _bridge(_LocalIOS(confidence=0.3), teacher=None)
    response = bridge.think("what is the capital of France?")
    assert "don't know enough" in response.answer
    assert bridge.status()["teacher"] == {"enabled": False}
