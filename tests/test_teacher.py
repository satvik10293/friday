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
        self.contexts = []

    def available(self):
        return True

    def ask(self, question, context=None):
        self.asked.append(question)
        self.contexts.append(context)
        if self.ok:
            return TeacherAnswer(ok=True, answer="Paris is the capital of France.",
                                 model="llama-test", latency_ms=42.0)
        return TeacherAnswer(ok=False, error="down")

    def status(self):
        return {"enabled": True, "available": True}


class _Memory:
    def __init__(self):
        self.remembered = []
        self.kwargs = []

    def recall(self, query, k=5):
        return []

    def remember(self, who, content, **kw):
        self.remembered.append(content)
        self.kwargs.append(kw)
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


# ── teacher context: follow-ups resolve, privacy is respected ─────────────────

def test_teacher_receives_the_conversation_window():
    teacher = _FakeTeacher()
    bridge = _bridge(_LocalIOS(confidence=0.3), teacher, _Memory())
    bridge.think("who founded SpaceX?")
    bridge.think("how old is he?")
    ctx = teacher.contexts[-1]
    turns = [t["text"] for t in ctx["recent_turns"]]
    assert any("SpaceX" in t for t in turns)       # the anchor for "he"


def test_private_memories_never_reach_the_teacher():
    class _ContextIOS(_LocalIOS):
        def think(self, command, context=None, **kw):
            r = super().think(command, context, **kw)
            r.context_used = {"memories": [
                {"id": 1, "content": "my password is hunter2", "private": True},
                {"id": 2, "content": "FRIDAY runs on Windows", "private": False},
                {"id": 3, "content": "unknown provenance"},       # no flag → local
            ]}
            return r

    teacher = _FakeTeacher()
    bridge = _bridge(_ContextIOS(confidence=0.3), teacher, _Memory())
    bridge.think("what OS do I use?")
    facts = teacher.contexts[-1]["facts"]
    assert facts == ["FRIDAY runs on Windows"]


def test_the_flywheel_taught_once_answered_locally_next_time(tmp_path):
    """The M30 acceptance criterion, end to end over the REAL stack: weak
    local answer → teacher consulted → answer learned into One Memory → the
    SAME question is answered locally next time, teacher asked exactly once.
    (Broken until M36: the execution cache keyed on context key-names only,
    so the second turn was served the stale pre-learning 'I don't know'.)"""
    from core.intelligence.service import IntelligenceOS
    from core.intelligence.store import IntelligenceStore
    from core.memory import HashingEmbedder, MemoryService, MemoryStore

    memory = MemoryService(store=MemoryStore(tmp_path / "mem.db"),
                           embedder=HashingEmbedder())
    ios = IntelligenceOS(store=IntelligenceStore(":memory:"),
                         memory_service=memory)
    teacher = _FakeTeacher()
    bridge = ConversationBridge(ios, decision_log=_Log(), teacher=teacher,
                                memory=memory,
                                speech=_SpeechOutput(synthesizer=lambda t: None),
                                speak_answers=False)

    first = bridge.think("what is the capital of France?")
    assert teacher.asked == ["what is the capital of France?"]
    assert "Paris" in first.answer

    second = bridge.think("what is the capital of France?")
    assert "Paris" in second.answer
    assert len(teacher.asked) == 1, \
        "teacher consulted again for a taught question — flywheel broken"
    assert "groq_teacher" not in bridge._decision_log.rows[-1]["route"]


def test_taught_answers_are_stored_with_the_question_as_topic():
    teacher = _FakeTeacher()
    memory = _Memory()
    bridge = _bridge(_LocalIOS(confidence=0.3), teacher, memory)
    bridge.think("what is the capital of France?")
    taught = [kw for c, kw in zip(memory.remembered, memory.kwargs) if "Paris" in c]
    assert taught and taught[0].get("topic") == "what is the capital of France?"
