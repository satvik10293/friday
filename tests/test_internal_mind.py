"""
M23 — Internal Mind (Phase D exit criteria, docs/FRIDAY_5X_ROADMAP.md;
directives 1, 2, 12, 13 of docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md).

FRIDAY produces inspectable thoughts between turns; thoughts expire and never
become memories by themselves; the Self Model answers "what can't I do and
why" truthfully; background cognition runs bounded, budgeted ticks that never
raise.
"""

from __future__ import annotations

import time

from core.cognition.background import BackgroundCognition
from core.cognition.thoughts import THOUGHT_KINDS, ThoughtStream
from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.self_model import SelfModel


# ── thought stream ────────────────────────────────────────────────────────────

def test_thoughts_are_bounded_and_inspectable():
    stream = ThoughtStream(capacity=5)
    for i in range(9):
        stream.think("observation", f"thought {i}")
    assert len(stream) == 5                       # ring buffer, oldest dropped
    recent = stream.recent(3)
    assert [t.text for t in recent] == ["thought 8", "thought 7", "thought 6"]
    snap = stream.snapshot()
    assert snap["generated"] == 9 and snap["live"] == 5


def test_thoughts_expire_automatically():
    stream = ThoughtStream()
    stream.think("reminder", "short-lived", ttl_s=0.05)
    stream.think("reminder", "long-lived", ttl_s=60)
    time.sleep(0.1)
    texts = [t.text for t in stream.recent()]
    assert "short-lived" not in texts and "long-lived" in texts


def test_unknown_kinds_become_observations_and_blank_thoughts_are_dropped():
    stream = ThoughtStream()
    t = stream.think("daydream", "hm")
    assert t.kind == "observation"
    stream.think("observation", "   ")
    assert len(stream) == 1
    assert set(THOUGHT_KINDS) >= {"observation", "hypothesis", "concern",
                                  "prediction", "reminder", "planning"}


# ── self model ────────────────────────────────────────────────────────────────

class _FakeModels:
    def loaded_models(self):
        class _M:
            class info:
                name = "friday-reasoner"
        return [_M()]

    def memory_usage_mb(self):
        return 12.0


class _FakeRegistry:
    def all(self):
        class _M:
            class info:
                capabilities = {"general", "coding"}
        return [_M()]


class _FakeIOS:
    models = _FakeModels()
    registry = _FakeRegistry()


def test_self_model_snapshot_aggregates_truthfully():
    model = SelfModel(ios=_FakeIOS())
    snap = model.snapshot()
    assert snap["models"]["loaded"] == ["friday-reasoner"]
    assert "coding" in snap["capabilities"]
    assert any("fully local" in lim for lim in snap["limitations"])


def test_self_model_answers_what_cant_i_do():
    answer = SelfModel(ios=_FakeIOS()).what_cant_i_do()
    assert "external services" in answer


def test_self_model_never_raises_with_no_backends():
    model = SelfModel()
    assert isinstance(model.snapshot(), dict)
    assert model.what_am_i_doing()
    assert model.what_can_i_do()


# ── background cognition ──────────────────────────────────────────────────────

class _FakeMemory:
    def __init__(self):
        self.consolidations = 0

    def consolidate(self, **kw):
        self.consolidations += 1
        return {"clusters": 0}

    def recall(self, query, k=8):
        return [{"topic": "spatial reasoning", "content": "x", "id": 1}]


def test_background_tick_is_bounded_and_observable():
    stream = ThoughtStream()
    memory = _FakeMemory()
    cognition = BackgroundCognition(thoughts=stream, memory=memory,
                                    self_model=SelfModel())
    report = cognition.tick()
    assert report["budget"] in ("full", "light")
    assert cognition.ticks == 1
    assert cognition.status()["last"] == report
    if report["budget"] == "full":
        assert memory.consolidations == 1
        assert any(t.kind == "hypothesis" for t in stream.recent())  # curiosity


def test_background_tick_survives_broken_subsystems():
    class Broken:
        def consolidate(self, **kw):
            raise RuntimeError("db locked")

        def recall(self, *a, **kw):
            raise RuntimeError("index gone")

    cognition = BackgroundCognition(thoughts=ThoughtStream(), memory=Broken())
    report = cognition.tick()                     # must not raise
    assert report["ms"] >= 0


# ── boot + conversation wiring ────────────────────────────────────────────────

def test_boot_brings_the_internal_mind_online():
    from core.launcher.startup import StartupSequence
    report = StartupSequence(headless=True, start_runtime=False).run()
    by_stage = {s.stage: s for s in report.stages}
    assert by_stage["mind"].status == "ok"
    assert report.components.get("thoughts") is not None
    assert report.components.get("self_model") is not None
    assert len(report.components["thoughts"]) >= 1     # the waking thought


class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


def test_self_questions_are_answered_from_the_self_model_not_the_llm():
    class NeverThinkIOS:
        def think(self, *a, **kw):
            raise AssertionError("the LLM must not be asked")

    bridge = ConversationBridge(
        NeverThinkIOS(), decision_log=_Log(), self_model=SelfModel(ios=_FakeIOS()),
        speech=_SpeechOutput(synthesizer=lambda t: None))
    response = bridge.think("what can't you do?")
    assert "external services" in response.answer
    assert bridge._decision_log.rows[0]["route"] == ["self_model"]
