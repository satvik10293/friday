"""
tests/test_neural_signals.py — M32.3/M32.4 base perfection.

Pins the neural-pipeline signal repairs:
  - last_answer_source(): the truthful local-vs-cloud signal.
  - Empath's computed tone feeds mood (a default "neutral" used to be passed).
  - record_turn() gets an honest positive/negative signal.
  - Sovereign extraction runs exactly once per turn, with truthful used_api
    (the old neural call was missing `intent` and threw on every turn).
"""

from types import SimpleNamespace

import pytest

import core.brain.friday_neural as neural


@pytest.fixture
def quiet_pipeline(monkeypatch):
    """Silence the heavy/branching collaborators of think_with_context."""
    import core.knowledge.friday_world as world
    import core.knowledge.friday_chronicle as chronicle
    import core.io.friday_visual as visual

    monkeypatch.setattr(world, "query_world", lambda *a, **k: [])
    monkeypatch.setattr(chronicle, "build_context_block", lambda *a, **k: "")
    monkeypatch.setattr(chronicle, "save_turn", lambda *a, **k: 0)
    monkeypatch.setattr(visual, "maybe_show", lambda *a, **k: None)
    monkeypatch.setattr(neural, "think", lambda *a, **k: "stub answer")
    monkeypatch.setattr(neural, "_emit_signal", lambda *a, **k: None)


@pytest.fixture
def fake_empath(monkeypatch):
    """Empath that reports a controllable tone."""
    import core.persona.friday_empath as empath

    state = {"tone": "neutral"}

    def fake_analyze(text, **kw):
        return SimpleNamespace(
            tone=state["tone"],
            response_temperature=0.4,
            response_max_tokens=200,
        )

    monkeypatch.setattr(empath, "analyze", fake_analyze)
    monkeypatch.setattr(empath, "build_tone_prompt", lambda s: "")
    return state


@pytest.fixture
def psyche_spy(monkeypatch):
    import core.persona.friday_psyche as psyche

    calls = {}
    monkeypatch.setattr(psyche, "record_turn",
                        lambda positive=True: calls.__setitem__("positive", positive))
    monkeypatch.setattr(psyche, "infer_mood_from_context",
                        lambda satvik_tone, task_type, session_len:
                        calls.__setitem__("satvik_tone", satvik_tone) or "neutral")
    monkeypatch.setattr(psyche, "update_mood", lambda m: None)
    return calls


@pytest.fixture
def sovereign_spy(monkeypatch):
    import core.knowledge.friday_sovereign as sovereign

    calls = []
    monkeypatch.setattr(sovereign, "run_background",
                        lambda **kw: calls.append(kw))
    return calls


# ── last_answer_source ─────────────────────────────────────────────────────────

def test_local_answer_sets_source_when_cloud_is_down(monkeypatch):
    """M42: the basic reasoner is the cloud — local answers (and sets the
    truthful 'local' source) only when every endpoint fails."""
    monkeypatch.setattr(neural, "_try_local", lambda q: "local knowledge answer")
    monkeypatch.setattr(neural, "_emit_notice", lambda m: None)
    monkeypatch.setattr(neural, "_record_turn", lambda *a: None)
    monkeypatch.setattr(neural, "_ENDPOINTS",
                        [SimpleNamespace(name="groq_primary", priority=1)])

    def _down(ep, *a, **k):
        raise RuntimeError("endpoint down")
    monkeypatch.setattr(neural, "_call_endpoint", _down)

    out = neural.think("what is FAISS?", allow_local=True)

    assert out == "local knowledge answer"
    assert neural.last_answer_source() == "local"
    assert neural.last_answer_was_local()


def test_cloud_preempts_a_confident_local_answer(monkeypatch):
    """M42: a confident local answer no longer short-circuits the chain."""
    monkeypatch.setattr(neural, "_try_local", lambda q: "local knowledge answer")
    monkeypatch.setattr(neural, "_emit_notice", lambda m: None)
    monkeypatch.setattr(neural, "_record_turn", lambda *a: None)
    monkeypatch.setattr(neural, "_maybe_learn", lambda *a: None)
    monkeypatch.setattr(neural, "_ENDPOINTS",
                        [SimpleNamespace(name="groq_primary", priority=1)])
    monkeypatch.setattr(neural, "_call_endpoint", lambda ep, *a, **k: "cloud answer")

    out = neural.think("what is FAISS?", allow_local=True)

    assert out == "cloud answer"
    assert neural.last_answer_source() == "cloud:groq_primary"


def test_cloud_answer_sets_source(monkeypatch):
    monkeypatch.setattr(neural, "_try_local", lambda q: None)
    monkeypatch.setattr(neural, "_emit_notice", lambda m: None)
    monkeypatch.setattr(neural, "_record_turn", lambda *a: None)
    monkeypatch.setattr(neural, "_maybe_learn", lambda *a: None)
    monkeypatch.setattr(neural, "_ENDPOINTS",
                        [SimpleNamespace(name="groq_primary", priority=1)])
    monkeypatch.setattr(neural, "_call_endpoint", lambda ep, *a, **k: "cloud answer")

    out = neural.think("hard question", allow_local=True)

    assert out == "cloud answer"
    assert neural.last_answer_source() == "cloud:groq_primary"
    assert not neural.last_answer_was_local()


# ── psyche wiring ──────────────────────────────────────────────────────────────

def test_empath_tone_reaches_mood(quiet_pipeline, fake_empath, psyche_spy, sovereign_spy):
    fake_empath["tone"] = "curious"
    neural.think_with_context("tell me about spatial indexes", tone="neutral")
    assert psyche_spy["satvik_tone"] == "curious", \
        "mood inference received the caller default, not Empath's tone"
    assert psyche_spy["positive"] is True


def test_frustrated_turn_is_negative_feedback(quiet_pipeline, fake_empath, psyche_spy, sovereign_spy):
    fake_empath["tone"] = "frustrated"
    neural.think_with_context("this is still broken")
    assert psyche_spy["positive"] is False, "trust can only ever rise otherwise"
    assert psyche_spy["satvik_tone"] == "frustrated"


# ── sovereign single ownership + truthful used_api ─────────────────────────────

def test_sovereign_called_once_with_intent(quiet_pipeline, fake_empath, psyche_spy, sovereign_spy):
    neural._set_answer_source("cloud:groq_primary")
    neural.think_with_context("q", task_type="question")
    assert len(sovereign_spy) == 1
    call = sovereign_spy[0]
    assert call["intent"] == "question"          # the old call omitted this
    assert call["used_api"] is True


def test_sovereign_skipped_when_brain_owns_extraction(quiet_pipeline, fake_empath, psyche_spy, sovereign_spy):
    neural.think_with_context("q", extract_knowledge=False)
    assert sovereign_spy == [], "double extraction: brain and neural both ran sovereign"


def test_sovereign_used_api_false_for_local(quiet_pipeline, fake_empath, psyche_spy, sovereign_spy, monkeypatch):
    def fake_think(*a, **k):
        neural._set_answer_source("local")
        return "local stub"

    monkeypatch.setattr(neural, "think", fake_think)
    neural.think_with_context("q")
    assert sovereign_spy[0]["used_api"] is False
