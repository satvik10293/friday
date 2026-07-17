"""
The notebook trick (M55): gap-driven knowledge distillation.

Every cloud answer proves a gap → the topic is queued → a background cycle asks
the teacher to TEACH it → the explanation becomes her own note (tagged
groq-distilled) → the next similar question is answered from the notebook,
locally, before any cloud call. Personal questions never become study topics.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.knowledge.distiller import KnowledgeDistiller, _topic_key
from core.launcher.conversation import ConversationBridge, _SpeechOutput


class _Teacher:
    def __init__(self, answer="Distilled explanation of the topic.", ok=True,
                 available=True):
        self._answer, self._ok, self._available = answer, ok, available
        self.asked = []

    def available(self):
        return self._available

    def ask(self, question, *, context=None):
        self.asked.append(question)
        return SimpleNamespace(ok=self._ok, answer=self._answer,
                               model="llama-3.3-70b-versatile", latency_ms=50.0)


class _Knowledge:
    def __init__(self, entries=None):
        self.stored = []
        self._entries = entries or []

    def remember_knowledge(self, title, content, **kw):
        self.stored.append({"title": title, "content": content, **kw})
        return SimpleNamespace(id="k-1", title=title, content=content)

    def search_knowledge(self, query, k=5):
        return self._entries


def _distiller(tmp_path, knowledge=None, teacher=None, **kw):
    return KnowledgeDistiller(knowledge, teacher,
                              queue_path=tmp_path / "queue.json", **kw)


# ── harvest side ──────────────────────────────────────────────────────────────

def test_cloud_answered_topic_is_queued(tmp_path):
    d = _distiller(tmp_path)
    assert d.note_gap("how does photosynthesis work?") is True
    assert d.status()["pending"] == 1


def test_personal_questions_are_never_queued(tmp_path):
    d = _distiller(tmp_path)
    assert d.note_gap("what is my wife's birthday?") is False
    assert d.status()["pending"] == 0
    assert d.skipped_personal == 1


def test_duplicate_topics_are_queued_once(tmp_path):
    d = _distiller(tmp_path)
    assert d.note_gap("how does photosynthesis work?") is True
    assert d.note_gap("how does photosynthesis work") is False   # same topic key
    assert d.status()["pending"] == 1


def test_trivial_chatter_is_not_studied(tmp_path):
    d = _distiller(tmp_path)
    assert d.note_gap("hello") is False
    assert d.note_gap("what's up") is False


def test_queue_survives_a_restart(tmp_path):
    _distiller(tmp_path).note_gap("how do black holes evaporate?")
    d2 = _distiller(tmp_path)                       # fresh process, same file
    assert d2.status()["pending"] == 1


# ── distil side ───────────────────────────────────────────────────────────────

def test_distill_teaches_the_topic_into_the_notebook(tmp_path):
    teacher, knowledge = _Teacher(), _Knowledge()
    d = _distiller(tmp_path, knowledge, teacher)
    d.note_gap("how does photosynthesis work?")
    assert d.distill_once() is True
    # the teacher was asked to TEACH, not just answer
    assert "teach" in teacher.asked[0].lower()
    note = knowledge.stored[0]
    assert note["source"] == "groq-distilled"        # provenance kept
    assert note["metadata"]["distilled_from"] == "how does photosynthesis work?"
    assert d.status()["pending"] == 0 and d.distilled == 1


def test_distilled_topic_is_never_requeued(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher())
    d.note_gap("how does photosynthesis work?")
    d.distill_once()
    assert d.note_gap("how does photosynthesis work?") is False  # already known


def test_failed_teaching_requeues_the_gap(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(ok=False))
    d.note_gap("how does photosynthesis work?")
    assert d.distill_once() is False
    assert d.status()["pending"] == 1                # gap kept for a later cycle


def test_run_cycle_is_bounded(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(), per_cycle=2)
    for topic in ["how do volcanoes form?", "why is the sky blue at noon?",
                  "how does gps positioning work?"]:
        d.note_gap(topic)
    assert d.run_cycle() == 2                        # bounded per cycle
    assert d.status()["pending"] == 1


def test_inert_without_teacher_or_knowledge(tmp_path):
    d = _distiller(tmp_path)                         # neither side present
    d.note_gap("how does photosynthesis work?")
    assert d.distill_once() is False and d.run_cycle() == 0


# ── consumption side: the notebook answers BEFORE the cloud ───────────────────

class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _GroundingIOS:
    """Grounds confidently on provided notebook knowledge."""
    def __init__(self):
        self.calls = []

    def think(self, prompt, context=None, **kw):
        self.calls.append({"prompt": prompt, "context": context, **kw})
        know = (context or {}).get("knowledge") or []
        ok = bool(know)
        return SimpleNamespace(
            task="general", strategy="grounded", ok=ok, confidence=0.8 if ok else 0.2,
            answer=(know[0]["content"] if know else ""), models_used=[],
            structured={}, trace_id="t", context_used=dict(context or {}))


class _CloudSpy:
    def __init__(self):
        self.called = 0

    def available(self):
        return True

    def reason(self, q, *, context=None):
        self.called += 1
        return SimpleNamespace(ok=True, answer="cloud answer", model="gpt-oss",
                               latency_ms=100.0)

    def status(self):
        return {"primary": "cloud", "called": self.called}


def test_notebook_answers_before_the_cloud(tmp_path):
    note = SimpleNamespace(id="k-1", title="how does photosynthesis work",
                           content="Photosynthesis converts light into sugar.",
                           confidence=0.7)
    knowledge = _Knowledge(entries=[note])
    cloud = _CloudSpy()
    bridge = ConversationBridge(
        _GroundingIOS(), decision_log=_Log(), knowledge=knowledge,
        reasoner=cloud, speech=_SpeechOutput(synthesizer=lambda t: None))
    resp = bridge.think("how does photosynthesis work?")
    assert "light into sugar" in resp.answer
    assert cloud.called == 0                          # the cloud was never phoned
    assert bridge.status()["notebook_turns"] == 1
    assert "notebook" in bridge._decision_log.rows[-1]["route"]


def test_uncovered_question_still_goes_to_the_cloud_and_queues_the_gap(tmp_path):
    d = _distiller(tmp_path)
    bridge = ConversationBridge(
        _GroundingIOS(), decision_log=_Log(), knowledge=_Knowledge(entries=[]),
        reasoner=_CloudSpy(), distiller=d,
        speech=_SpeechOutput(synthesizer=lambda t: None))
    bridge.think("how does quantum tunneling work?")
    assert bridge.status()["cloud_turns"] == 1
    assert d.status()["pending"] == 1                 # the gap was harvested


def test_topic_key_is_order_insensitive():
    assert _topic_key("how does photosynthesis work") == \
        _topic_key("photosynthesis — how does it work?")
