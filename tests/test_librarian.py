"""
M40 — the librarian: world knowledge from a real reference source.

When both local passes stay weak, FRIDAY looks the question up through the
M7 documentation bridge (wikipedia fetcher) and grounds HER OWN reader on
the fetched extract — provenance over generation. The distilled extract is
learned back as validated knowledge, so the next similar question is
answered locally. Only when the library has nothing does the Groq teacher
speak. Personal-shaped questions never trigger a fetch.

No network is touched anywhere in these tests.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.knowledge.world_fetcher import _topicize
from core.launcher.conversation import ConversationBridge, _SpeechOutput

_EXTRACT = ("The Moon is Earth's only natural satellite, orbiting at an "
            "average distance of 384,400 km.")


# ── topic extraction ──────────────────────────────────────────────────────────

def test_topicize_strips_question_scaffolding():
    assert _topicize("how far away is the moon?") == "moon"
    assert _topicize("Who is Marie Curie") == "Marie Curie"
    assert _topicize("tell me about black holes") == "black holes"
    assert _topicize("what is the speed of light?") == "speed of light"


# ── fakes (mirroring test_teacher.py) ─────────────────────────────────────────

class _Response:
    def __init__(self, confidence, answer):
        self.task = "general"
        self.strategy = "chain_of_thought"
        self.ok = True
        self.answer = answer
        self.confidence = confidence
        self.models_used = ["friday-reasoner"]
        self.structured = {}
        self.trace_id = None


class _IOS:
    """Weak on its own knowledge; strong when handed librarian evidence."""

    def __init__(self, grounded_confidence=0.8):
        self.calls = []
        self._grounded = grounded_confidence

    def think(self, command, context=None, collaborate=False, **kw):
        self.calls.append({"context": context, "collaborate": collaborate})
        if context and context.get("knowledge"):
            return _Response(self._grounded, "The Moon is 384,400 km away.")
        return _Response(0.3, "I don't know enough about that yet.")


class _Knowledge:
    def __init__(self, extract=_EXTRACT):
        self.extract = extract
        self.resolves = []
        self.learned = []

    def resolve(self, query, allow_external=False, **kw):
        self.resolves.append((query, allow_external))
        if self.extract is None:
            return {"source": "none", "entries": [], "candidate": None}
        return {"source": "external", "entries": [],
                "candidate": SimpleNamespace(title="Moon", content=self.extract)}

    def learn(self, text, **kw):
        self.learned.append((text, kw))
        return SimpleNamespace(title=kw.get("title"))


class _Teacher:
    def __init__(self):
        self.asked = []

    def available(self):
        return True

    def ask(self, question, context=None):
        self.asked.append(question)
        return SimpleNamespace(ok=True, answer="teacher answer",
                               model="llama-test", latency_ms=1.0)

    def status(self):
        return {"enabled": True}


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


def _bridge(ios=None, knowledge=None, teacher=None):
    return ConversationBridge(
        ios if ios is not None else _IOS(), decision_log=_Log(),
        knowledge=knowledge, teacher=teacher,
        speech=_SpeechOutput(synthesizer=lambda t: None), speak_answers=False)


# ── the librarian path ────────────────────────────────────────────────────────

def test_weak_answer_is_grounded_on_the_fetched_reference():
    knowledge, teacher = _Knowledge(), _Teacher()
    bridge = _bridge(knowledge=knowledge, teacher=teacher)
    response = bridge.think("how far away is the moon?")
    assert "384,400" in response.answer
    assert knowledge.resolves == [("how far away is the moon?", True)]
    assert teacher.asked == []                     # the library answered first
    row = bridge._decision_log.rows[0]
    assert "librarian" in row["route"]
    assert bridge.status()["librarian_turns"] == 1


def test_librarian_answers_are_learned_back_as_knowledge():
    knowledge = _Knowledge()
    bridge = _bridge(knowledge=knowledge)
    bridge.think("how far away is the moon?")
    assert len(knowledge.learned) == 1
    text, kw = knowledge.learned[0]
    assert "384,400" in text
    assert kw.get("source") == "wikipedia"


def test_empty_library_falls_back_to_the_teacher():
    knowledge, teacher = _Knowledge(extract=None), _Teacher()
    bridge = _bridge(knowledge=knowledge, teacher=teacher)
    response = bridge.think("how far away is the moon?")
    assert response.answer == "teacher answer"
    assert teacher.asked == ["how far away is the moon?"]
    assert "librarian" not in bridge._decision_log.rows[0]["route"]


def test_unconvincing_grounding_falls_back_to_the_teacher():
    """If her reader stays unsure even WITH the reference, the extract is
    neither spoken nor learned — no confident-sounding garbage."""
    knowledge, teacher = _Knowledge(), _Teacher()
    bridge = _bridge(ios=_IOS(grounded_confidence=0.3),
                     knowledge=knowledge, teacher=teacher)
    response = bridge.think("how far away is the moon?")
    assert response.answer == "teacher answer"
    assert knowledge.learned == []


def test_personal_questions_never_reach_the_library():
    knowledge, teacher = _Knowledge(), _Teacher()
    bridge = _bridge(knowledge=knowledge, teacher=teacher)
    bridge.think("when is my birthday according to what I told you")
    assert knowledge.resolves == []                # nothing left the box
    assert bridge.status()["librarian_turns"] == 0


def test_strong_local_answers_skip_the_library_entirely():
    class ConfidentIOS(_IOS):
        def think(self, command, context=None, **kw):
            return _Response(0.9, "local answer")

    knowledge = _Knowledge()
    bridge = _bridge(ios=ConfidentIOS(), knowledge=knowledge)
    bridge.think("how far away is the moon?")
    assert knowledge.resolves == []


def test_no_knowledge_service_means_the_old_chain_is_unchanged():
    teacher = _Teacher()
    bridge = _bridge(knowledge=None, teacher=teacher)
    response = bridge.think("how far away is the moon?")
    assert response.answer == "teacher answer"
