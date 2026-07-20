"""
Constant learning (M62): the curiosity drive keeps her studying on her own.

The distiller only learns REACTIVELY — from gaps the owner's questions expose.
When no one is asking, its queue empties and she stops growing. CuriosityEngine
fixes that: whenever the study queue runs low it refills it autonomously from a
practical curriculum (and follow-ups off what she just learned), bounded by a
per-day budget so the teacher quota is never surprised. Personal topics never
enter learning (the distiller's guard holds), and it never raises.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.knowledge.curiosity import CuriosityEngine, _DEFAULT_CURRICULUM
from core.knowledge.distiller import KnowledgeDistiller


class _Teacher:
    def __init__(self, available=True, ok=True, answer="a\nb\nc"):
        self._available, self._ok, self._answer = available, ok, answer
        self.asked = []

    def available(self):
        return self._available

    def ask(self, question, *, context=None):
        self.asked.append(question)
        return SimpleNamespace(ok=self._ok, answer=self._answer,
                               model="teacher", latency_ms=1.0)


class _Knowledge:
    """Minimal knowledge service: nothing known unless seeded with entries."""

    def __init__(self, entries=None):
        self._entries = entries or []

    def search_knowledge(self, query, k=5):
        return self._entries


def _distiller(tmp_path, knowledge=None, teacher=None):
    return KnowledgeDistiller(knowledge, teacher,
                              queue_path=tmp_path / "queue.json")


def _engine(tmp_path, distiller, **kw):
    kw.setdefault("state_path", tmp_path / "curiosity.json")
    kw.setdefault("knowledge", getattr(distiller, "knowledge", None))
    return CuriosityEngine(distiller, **kw)


# ── the drive tops the queue up when it runs low ─────────────────────────────

def test_refill_seeds_topics_when_the_queue_is_empty(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    eng = _engine(tmp_path, d, min_queue=3)
    queued = eng.refill()
    assert queued > 0
    assert d.status()["pending"] == queued
    assert eng.proposed == queued


def test_refill_is_a_noop_when_the_queue_is_already_full(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    # pre-fill the queue past the threshold
    d.seed(["how neural networks learn", "how git branching works",
            "how dns resolves a domain", "how tls secures a connection"])
    before = d.status()["pending"]
    eng = _engine(tmp_path, d, min_queue=3)
    assert eng.refill() == 0
    assert d.status()["pending"] == before


# ── the per-day budget bounds how much enters learning ────────────────────────

def test_daily_budget_caps_new_topics(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    eng = _engine(tmp_path, d, min_queue=99, per_refill=99, max_per_day=5)
    total = 0
    for _ in range(10):                 # keep asking; queue stays "low"
        total += eng.refill()
    assert total == 5                   # never exceeds the daily budget
    assert eng.refill() == 0            # budget exhausted → no-op


def test_zero_budget_learns_nothing(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    eng = _engine(tmp_path, d, max_per_day=0)
    assert eng.refill() == 0
    assert d.status()["pending"] == 0


# ── it skips what she already knows and never queues personal topics ──────────

def test_already_known_curriculum_topics_are_skipped(tmp_path):
    # she already knows every curriculum topic → nothing new to queue
    known = [SimpleNamespace(title=t, source="groq-distilled")
             for t in _DEFAULT_CURRICULUM]
    d = _distiller(tmp_path, _Knowledge(known), _Teacher(available=False))
    eng = _engine(tmp_path, d, min_queue=3,
                  curriculum=["how neural networks learn from data"])
    assert eng.refill() == 0


def test_personal_topics_never_enter_learning(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    eng = _engine(tmp_path, d, min_queue=3,
                  curriculum=["what is my wife's birthday",
                              "how neural networks learn from data"])
    eng.refill()
    # the personal topic was dropped by the distiller's guard
    assert d.skipped_personal >= 1
    for gap in d._queue:
        assert "birthday" not in gap["topic"]


# ── curriculum is the practical syllabus, and state persists ──────────────────

def test_default_curriculum_is_practical_not_trivia(tmp_path):
    joined = " ".join(_DEFAULT_CURRICULUM).lower()
    assert "python" in joined and "neural network" in joined
    assert "debug" in joined and "big-o" in joined
    # no encyclopedia trivia
    assert "photosynthesis" not in joined and "seasons" not in joined


def test_budget_and_position_survive_a_restart(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    eng = _engine(tmp_path, d, min_queue=99, per_refill=3, max_per_day=10)
    eng.refill()
    spent, pos = eng._today, eng._cur_idx
    assert spent > 0
    # a fresh engine over the same state file resumes where it left off
    eng2 = _engine(tmp_path, _distiller(tmp_path, _Knowledge(),
                                        _Teacher(available=False)),
                   min_queue=99, per_refill=3, max_per_day=10)
    assert eng2._today == spent
    assert eng2._cur_idx == pos


def test_refill_never_raises_on_a_broken_distiller(tmp_path):
    class _Broken:
        teacher = None

        def status(self):
            raise RuntimeError("boom")

        def seed(self, topics):
            raise RuntimeError("boom")

    eng = _engine(tmp_path, _Broken())
    assert eng.refill() == 0          # swallowed, returns 0


def test_status_reports_the_learning_drive(tmp_path):
    d = _distiller(tmp_path, _Knowledge(), _Teacher(available=False))
    eng = _engine(tmp_path, d, max_per_day=20)
    eng.refill()
    s = eng.status()
    assert s["max_per_day"] == 20
    assert s["proposed"] >= 1
    assert s["curriculum_size"] == len(_DEFAULT_CURRICULUM)
