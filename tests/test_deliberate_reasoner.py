"""
Her own deliberate reasoning brain (M54).

The intelligence is the ARCHITECTURE — exact-first arithmetic, decomposition,
working memory, tool-grounded steps, self-consistency — not the substrate.
These tests pin that architecture with a scripted stub substrate, so the
reasoning is verified with zero model download. The headline property: exact
truth (arithmetic) is COMPUTED, never left to the language faculty — so even a
substrate that lies about math produces the right answer.
"""

from __future__ import annotations

from core.reasoning import DeliberateReasoner, build_reasoner
from core.reasoning.substrate import ModelTeamSubstrate


class _Sub:
    """Scripted substrate. `replies` maps a prompt-substring → reply; anything
    unmatched returns `default`. Records every prompt it sees."""

    def __init__(self, replies=None, default="", available=True):
        self._replies = replies or {}
        self._default = default
        self._available = available
        self.prompts = []

    def available(self):
        return self._available

    def generate(self, prompt, *, context=None, temperature=0.3):
        self.prompts.append(prompt)
        # most specific (longest) matching needle wins, so a worked step echoed
        # inside a later synthesis prompt can't shadow the synthesis reply
        for needle in sorted(self._replies, key=len, reverse=True):
            if needle.lower() in prompt.lower():
                return self._replies[needle]
        return self._default


# ── exact truth: arithmetic is computed, never guessed ────────────────────────

def test_arithmetic_is_computed_not_generated():
    # the substrate would LIE (says 5); the engine must compute 4 itself
    sub = _Sub(default="the answer is 5")
    brain = DeliberateReasoner(sub)
    ans = brain.reason("what is 2 + 2?")
    assert ans.ok and ans.answer == "2 + 2 = 4"
    assert sub.prompts == []                     # substrate never even consulted
    assert brain.exact_answers == 1


def test_more_arithmetic_shapes():
    brain = DeliberateReasoner(_Sub())
    assert brain.reason("calculate 12 * 12").answer == "12 * 12 = 144"
    assert brain.reason("how much is 100 - 37?").answer == "100 - 37 = 63"


def test_percent_and_power_are_computed():
    brain = DeliberateReasoner(_Sub(default="wrong"))
    assert brain.reason("what is 15% of 200?").answer == "15% of 200 = 30"
    assert brain.reason("compute 2 to the power of 10").answer == "2^10 = 1024"
    assert brain.reason("what is 3^4?").answer == "3^4 = 81"


def test_a_year_is_not_mistaken_for_a_calculation():
    # no operator, no calc intent → not "solved"; falls to reasoning
    sub = _Sub(default="Ada Lovelace, in the 1840s.")
    brain = DeliberateReasoner(sub, decompose=False)
    ans = brain.reason("who wrote the first program in 1843?")
    assert ans.answer == "Ada Lovelace, in the 1840s."


# ── decomposition + working memory + synthesis ────────────────────────────────

def test_decompose_work_and_synthesize():
    # a genuinely complex question ("explain … and then …") earns System-2 depth
    sub = _Sub(replies={
        "break the following question": "find the two numbers\nadd them",
        "add them": "they add to 30",
        "using these steps": "The total is 30.",
    }, default="10 and 20")
    brain = DeliberateReasoner(sub, decompose=True)
    ans = brain.reason("explain how to find the numbers and then add them")
    assert ans.ok and ans.answer == "The total is 30."
    # the plan was requested, steps were worked, and a synthesis prompt ran
    assert any("break the following question" in p.lower() for p in sub.prompts)
    assert any("using these steps" in p.lower() for p in sub.prompts)


def test_math_step_inside_a_plan_is_computed_exactly():
    # a decomposed step that is arithmetic must be COMPUTED, not sent to the substrate
    sub = _Sub(replies={
        "break the following question": "compute 6 * 7\nstate the result",
        "using these steps": "It is 42.",
    }, default="unsure")
    brain = DeliberateReasoner(sub, decompose=True)
    ans = brain.reason("explain how to work out six sevens step by step")
    assert ans.ok and ans.answer == "It is 42."
    assert brain.math_steps == 1
    # the arithmetic step never went to the substrate as a solve prompt
    assert not any("give only its result: compute 6 * 7" in p.lower()
                   for p in sub.prompts)


def test_simple_questions_stay_system_1_no_decomposition():
    # a short/simple question must NOT be decomposed (no over-thinking)
    sub = _Sub(default="Claude.")
    brain = DeliberateReasoner(sub, decompose=True)
    ans = brain.reason("who are you?")
    assert ans.answer == "Claude."
    assert not any("break the following question" in p.lower() for p in sub.prompts)


# ── self-consistency verification ─────────────────────────────────────────────

def test_self_consistency_keeps_the_majority_answer():
    class _Drift:
        """First synthesis says 42; later (hotter) runs drift to 7 then 42."""
        def __init__(self):
            self.n = 0
        def available(self):
            return True
        def generate(self, prompt, *, context=None, temperature=0.3):
            if "using these steps" not in prompt.lower():
                return "step"           # plan/step prompts
            self.n += 1
            return {1: "42", 2: "7", 3: "42"}.get(self.n, "42")
    brain = DeliberateReasoner(_Drift(), self_consistency=3)
    ans = brain.reason("explain why and how the result comes out?")
    assert ans.answer == "42"           # 2 votes for 42 beat 1 for 7


# ── availability + factory ────────────────────────────────────────────────────

def test_unavailable_substrate_makes_the_brain_unavailable():
    brain = DeliberateReasoner(_Sub(available=False))
    assert brain.available() is False
    assert brain.reason("anything").ok is False


def test_build_reasoner_falls_back_to_the_model_team():
    class _IOS:
        def think(self, prompt, context=None, **kw):
            class R:
                ok = True; answer = "team answer"
            return R()
    brain = build_reasoner(local_reasoner=None, ios=_IOS())
    assert isinstance(brain, DeliberateReasoner)
    assert isinstance(brain.substrate, ModelTeamSubstrate)
    assert brain.available() is True


def test_build_reasoner_is_none_without_any_substrate():
    assert build_reasoner(local_reasoner=None, ios=None) is None


# ── honest confidence: weak defers, exact + strong stand ──────────────────────

class _CalibratedSub(_Sub):
    def __init__(self, base, **kw):
        super().__init__(**kw)
        self.base_confidence = base


def test_weak_substrate_reports_low_confidence_so_the_answer_defers():
    # the model team (base 0.5) should NOT be trusted to stand alone on prose
    brain = DeliberateReasoner(_CalibratedSub(0.5, default="maybe this"))
    ans = brain.reason("who painted the ceiling?")
    assert ans.ok and ans.confidence <= 0.55        # → the bridge will escalate


def test_strong_substrate_reports_high_confidence():
    brain = DeliberateReasoner(_CalibratedSub(0.78, default="Michelangelo."))
    ans = brain.reason("who painted the ceiling?")
    assert ans.confidence >= 0.75                    # stands on its own


def test_exact_math_is_full_confidence_regardless_of_substrate():
    brain = DeliberateReasoner(_CalibratedSub(0.2, default="lies"))
    ans = brain.reason("what is 9 * 9?")
    assert ans.answer == "9 * 9 = 81" and ans.confidence == 1.0
