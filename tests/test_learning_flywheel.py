"""
The learning flywheel (completed): recurring experience -> durable, recallable,
persisted lessons, via LearningService + LearningBrain. Proves the loop the
Learning Brain used to leave open — it now keeps what it notices.
"""

from __future__ import annotations

from core.brains.learning.brain import LearningBrain
from core.services.learning_service import LearningService


class _Services:
    """Minimal service locator the brain resolves through (services.try_get)."""
    def __init__(self, learning):
        self._learning = learning

    def try_get(self, name):
        return self._learning if name == "learning" else None


# ── the service: learn / reinforce / recall / persist ─────────────────────────

def test_learn_creates_then_reinforces_a_lesson(tmp_path):
    svc = LearningService(path=tmp_path / "lessons.json")
    first = svc.learn("tracking:person", kind="tracking", category="person")
    assert first["new"] is True and first["reinforcement"] == 1
    again = svc.learn("tracking:person")
    assert again["new"] is False and again["reinforcement"] == 2


def test_lessons_are_recallable_strongest_first(tmp_path):
    svc = LearningService(path=tmp_path / "lessons.json")
    svc.learn("a:x"); svc.learn("b:y"); svc.learn("b:y"); svc.learn("b:y")
    lessons = svc.lessons()
    assert [l["pattern"] for l in lessons][0] == "b:y"        # most reinforced first
    assert svc.lessons(min_reinforcement=3) == [l for l in lessons if l["pattern"] == "b:y"]


def test_lessons_survive_a_restart(tmp_path):
    store = tmp_path / "lessons.json"
    LearningService(path=store).learn("tracking:person", kind="tracking")
    # a fresh instance over the same file = a new session
    reborn = LearningService(path=store)
    recalled = reborn.lessons()
    assert len(recalled) == 1 and recalled[0]["pattern"] == "tracking:person"


def test_persist_false_keeps_it_in_memory_only(tmp_path):
    svc = LearningService(path=tmp_path / "lessons.json", persist=False)
    svc.learn("a:x")
    assert not (tmp_path / "lessons.json").exists()
    assert LearningService(path=tmp_path / "lessons.json").lessons() == []


# ── the brain: promote recurring experience into a lesson, no tick inflation ──

def _feed(svc, n, kind="tracking", category="person"):
    for _ in range(n):
        svc.record(kind, {"category": category})


def test_brain_promotes_a_recurring_pattern_into_a_persisted_lesson(tmp_path):
    svc = LearningService(path=tmp_path / "lessons.json")
    brain = LearningBrain(services=_Services(svc))
    _feed(svc, 3)                                    # 3 sightings = enough to learn
    report = brain.tick()

    lessons = svc.lessons()
    assert len(lessons) == 1 and lessons[0]["pattern"] == "tracking:person"
    # it persisted — a new session still knows it
    assert LearningService(path=tmp_path / "lessons.json").lessons()[0]["pattern"] == "tracking:person"
    # and the brain announced the new lesson
    assert report is not None and "lesson" in report.summary.lower()


def test_idle_ticks_do_not_re_learn(tmp_path):
    svc = LearningService(path=tmp_path / "lessons.json")
    brain = LearningBrain(services=_Services(svc))
    _feed(svc, 3)
    brain.tick()
    r0 = svc.lessons()[0]["reinforcement"]
    for _ in range(8):                               # idle: no new experience
        brain.tick()
    assert svc.lessons()[0]["reinforcement"] == r0, "a lesson was re-learned on idle ticks"

    _feed(svc, 1)                                    # real new experience
    brain.tick()
    assert svc.lessons()[0]["reinforcement"] == r0 + 1, "new experience did not reinforce"


def test_brain_health_is_real_not_placeholder(tmp_path):
    svc = LearningService(path=tmp_path / "lessons.json")
    brain = LearningBrain(services=_Services(svc))
    _feed(svc, 3)
    brain.tick()
    h = brain.health()
    assert h["status"] == "ok"
    assert h["lessons"] == 1
