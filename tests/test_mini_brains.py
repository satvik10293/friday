"""
tests/test_mini_brains.py — M33 Mini-Brain Fast Path.

Every mini brain answers its task shape exactly, in well under its 500 ms
budget, and refuses (returns None / no claim) anything outside its
competence — a wrong fast answer is worse than a slow correct one.
"""

import time
from types import SimpleNamespace

import pytest

from core.intelligence.mini_brains import (
    ClockBrain, MathBrain, MiniBrainCortex, RecallBrain, SystemBrain, UnitBrain,
)


# ── correctness ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prompt,expected", [
    ("what is 2+2", "4"),
    ("What's 12 * 7 + 1?", "85"),
    ("calculate 100 / 8", "12.5"),
    ("how much is 15% of 80", "12"),
    ("2^10", "1024"),
])
def test_math_brain_answers(prompt, expected):
    assert MathBrain().answer(prompt) == expected


@pytest.mark.parametrize("prompt,expected", [
    ("what is 12 times 7", "84"),                 # STT transcribes words…
    ("what is 100 divided by 8", "12.5"),
    ("what's 19 plus 23", "42"),
    ("what is 50 minus 8", "42"),
    ("what is 2 to the power of 10", "1024"),
    ("what is 5 x 3", "15"),
    ("what is 15 percent of 80", "12"),           # …and "percent", not "%"
])
def test_math_brain_understands_spoken_operators(prompt, expected):
    assert MathBrain().answer(prompt) == expected


@pytest.mark.parametrize("prompt", [
    "what is love",                      # no arithmetic
    "tell me about python",              # no numbers
    "call 555-2368 now",                 # digits but no computation intent
    "how many times did I ask you",      # "times" without digits around it
    "hand it over 2 me",                 # "over" not between digits
])
def test_math_brain_refuses_non_math(prompt):
    assert MathBrain().claim(prompt) == 0.0


def test_math_brain_rejects_dangerous_input():
    assert MathBrain().answer("what is __import__('os').system('x')") is None
    assert MathBrain().answer("what is 9**999") is None   # exponent bound


def test_clock_brain():
    brain = ClockBrain()
    assert brain.claim("what time is it?") > 0.6
    assert ":" in brain.answer("what time is it?")
    assert brain.claim("what day is it") > 0.6
    assert brain.claim("set a timer for 5 minutes") == 0.0


@pytest.mark.parametrize("prompt,contains", [
    ("convert 10 km to miles", "6.2137"),
    ("100 kg in pounds", "220.46"),
    ("0 celsius to fahrenheit", "32"),
    ("212 f in c", "100"),
])
def test_unit_brain_converts(prompt, contains):
    answer = UnitBrain().answer(prompt)
    assert answer is not None and contains in answer


@pytest.mark.parametrize("prompt,contains", [
    ("how many miles is 5 km", "3.1069"),         # spoken target-first phrasing
    ("how many pounds in 3 kg", "6.6139"),
    ("how many feet are 2 meters", "6.5617"),
])
def test_unit_brain_understands_target_first_phrasing(prompt, contains):
    answer = UnitBrain().answer(prompt)
    assert answer is not None and contains in answer


def test_clock_brain_date_phrasings():
    brain = ClockBrain()
    for prompt in ("what date is it", "what date is it today", "what's the date"):
        assert brain.claim(prompt) > 0.6, prompt
        assert str(__import__("datetime").datetime.now().year) in brain.answer(prompt)


def test_unit_brain_refuses_unknown_pairs():
    assert UnitBrain().claim("convert 10 dollars to euros") == 0.0


def test_system_brain_reports(monkeypatch):
    pytest.importorskip("psutil")
    brain = SystemBrain()
    assert brain.claim("how much ram usage right now?") > 0.6
    answer = brain.answer("what's the memory usage?")
    assert answer is not None and "RAM" in answer.upper()
    assert brain.claim("buy more ram sticks") == 0.0   # no question shape


def test_recall_brain_reads_chronicle(monkeypatch):
    import core.knowledge.friday_chronicle as chronicle

    monkeypatch.setattr(chronicle, "search_keyword",
                        lambda topic, limit=3: [{"content": "Satvik is building FRIDAY"}])
    answer = RecallBrain().answer("do you remember my project?")
    assert answer is not None and "Satvik is building FRIDAY" in answer


def test_recall_brain_silent_on_empty_memory(monkeypatch):
    import core.knowledge.friday_chronicle as chronicle

    monkeypatch.setattr(chronicle, "search_keyword", lambda topic, limit=3: [])
    assert RecallBrain().answer("do you remember the moon mission?") is None


class _FakeMemory:
    """Stands in for the One Memory service's recall()."""

    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def recall(self, query, k=8):
        self.queries.append(query)
        return self.rows


def test_recall_brain_prefers_one_memory_over_chronicle(monkeypatch):
    import core.knowledge.friday_chronicle as chronicle

    monkeypatch.setattr(chronicle, "search_keyword",
                        lambda topic, limit=3: [{"content": "stale chronicle row"}])
    memory = _FakeMemory([{"content": "The Moon is 384,400 km away.", "score": 0.8}])
    answer = RecallBrain(memory=memory).answer("what do you know about the moon?")
    assert answer is not None
    assert "384,400" in answer and "stale chronicle" not in answer
    assert memory.queries == ["the moon"]


def test_recall_brain_filters_irrelevant_one_memory_hits(monkeypatch):
    """Top-k always returns SOMETHING — low-similarity rows must not be spoken.
    With One Memory empty of relevant rows, the chronicle fallback still runs."""
    import core.knowledge.friday_chronicle as chronicle

    monkeypatch.setattr(chronicle, "search_keyword", lambda topic, limit=3: [])
    memory = _FakeMemory([{"content": "grocery list: eggs, milk", "score": 0.05}])
    assert RecallBrain(memory=memory).answer("do you remember the mars rover?") is None


def test_cortex_wires_memory_into_recall_brain():
    memory = _FakeMemory([])
    cortex = MiniBrainCortex(memory=memory)
    recall = next(b for b in cortex.brains if b.name == "recall")
    assert recall._memory is memory


# ── the budget ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "what is 355/113",
    "what time is it",
    "convert 5 km to miles",
])
def test_mini_answers_are_under_budget(prompt):
    cortex = MiniBrainCortex()
    t0 = time.perf_counter()
    result = cortex.try_answer(prompt)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    assert result is not None
    assert result.elapsed_ms < 500, f"{result.brain} blew the budget: {result.elapsed_ms:.0f}ms"
    assert wall_ms < 500


def test_budget_violation_is_counted_not_hidden():
    class SlowBrain(ClockBrain):
        name = "slow"
        budget_ms = 1.0

        def answer(self, prompt):
            time.sleep(0.01)
            return "late answer"

    cortex = MiniBrainCortex(brains=[SlowBrain()])
    result = cortex.try_answer("what time is it")
    assert result is not None and result.answer == "late answer"
    assert cortex.stats()["slow"]["budget_violations"] == 1


# ── cortex routing ─────────────────────────────────────────────────────────────

def test_cortex_picks_the_right_brain():
    cortex = MiniBrainCortex()
    assert cortex.try_answer("what is 3*3").brain == "math"
    assert cortex.try_answer("what time is it").brain == "clock"
    assert cortex.try_answer("9 kg to lbs").brain == "units"


def test_cortex_declines_open_questions():
    cortex = MiniBrainCortex()
    assert cortex.try_answer("why is the sky blue?") is None
    assert cortex.try_answer("write me a poem about rust") is None
    assert cortex.try_answer("") is None


def test_crashing_brain_never_breaks_a_turn():
    class BrokenBrain(MathBrain):
        name = "broken"

        def answer(self, prompt):
            raise RuntimeError("boom")

    cortex = MiniBrainCortex(brains=[BrokenBrain()])
    assert cortex.try_answer("what is 1+1") is None
    assert cortex.stats()["broken"]["misses"] == 1


# ── IOS integration ────────────────────────────────────────────────────────────

@pytest.fixture
def ios_no_models():
    from core.intelligence.service import IntelligenceOS
    from core.intelligence.store import IntelligenceStore

    return IntelligenceOS(store=IntelligenceStore(":memory:"), bootstrap=False)


def test_ios_fast_path_answers_without_models(ios_no_models):
    response = ios_no_models.think("what is 6*7")
    assert response.ok
    assert response.answer == "42"
    assert response.strategy == "mini:math"
    assert response.models_used == []
    assert response.trace_id


def test_ios_open_question_falls_through_to_router(ios_no_models, monkeypatch):
    routed = {}

    def fake_route(prompt, **kw):
        routed["prompt"] = prompt
        from core.intelligence.router import RouterResponse
        return RouterResponse(task="general", complexity="simple",
                              strategy="direct", ok=True, answer="routed",
                              confidence=0.7)

    monkeypatch.setattr(ios_no_models.router, "route", fake_route)
    response = ios_no_models.think("explain event buses", build_context=False)
    assert response.answer == "routed"
    assert routed["prompt"] == "explain event buses"


def test_ios_mini_brains_can_be_disabled(ios_no_models, monkeypatch):
    from core.intelligence.router import RouterResponse

    monkeypatch.setattr(
        ios_no_models.router, "route",
        lambda prompt, **kw: RouterResponse(task="math", complexity="simple",
                                            strategy="direct", ok=True,
                                            answer="model answer", confidence=0.7))
    response = ios_no_models.think("what is 6*7", build_context=False,
                                   use_mini_brains=False)
    assert response.answer == "model answer"


def test_ios_status_exposes_cortex_stats(ios_no_models):
    ios_no_models.think("what is 1+1")
    stats = ios_no_models.status()["mini_brains"]
    assert stats["math"]["hits"] == 1
