"""
SHE is the reasoning model (M56).

Three pillars, all model-free:
1. symbolic deduction in exact.py — syllogisms and transitive relation chains,
   deduced from the stated premises, refused when not entailed
2. the NativeMind — her own language faculty: extractive composition over HER
   knowledge/memory with coverage-based confidence; defers honestly when her
   notes don't cover the question
3. routing — her own deliberate mind answers BEFORE the cloud; the cloud is
   demoted to a fallback teacher
"""

from __future__ import annotations

from types import SimpleNamespace

from core.reasoning import DeliberateReasoner, build_reasoner, exact
from core.reasoning.native import NativeMind
from core.launcher.conversation import ConversationBridge, _SpeechOutput


# ── 1. symbolic deduction: real reasoning, zero models ────────────────────────

def test_syllogism_single_hop():
    out = exact.solve("All cats are animals. Sam is a cat. Is Sam an animal?")
    assert out.startswith("Yes") and "Sam is a cat" in out


def test_syllogism_multi_hop_chain():
    out = exact.solve("All cats are mammals. All mammals are animals. "
                      "Sam is a cat. Is Sam an animal?")
    assert out.startswith("Yes") and "every mammal is an animal" in out


def test_syllogism_negative_via_disjointness():
    out = exact.solve("No fish are mammals. All whales are mammals. "
                      "Moby is a whale. Is Moby a fish?")
    assert out.startswith("No") and "not a fish" in out


def test_syllogism_refuses_what_premises_dont_entail():
    assert exact.solve("All cats are animals. Sam is a dog. Is Sam a cat?") is None
    assert exact.solve("Is Paris a city?") is None            # no premises


def test_transitive_relations_superlative_and_query():
    q = "Tom is taller than Sam. Sam is taller than Ann. "
    assert "Tom is the tallest" in exact.solve(q + "Who is the tallest?")
    assert "Ann is the shortest" in exact.solve(q + "Who is the shortest?")
    assert exact.solve(q + "Is Tom taller than Ann?").startswith("Yes")
    assert exact.solve(q + "Is Ann taller than Tom?").startswith("No")


def test_relations_mixed_poles_unify():
    out = exact.solve("Ann is shorter than Sam. Tom is taller than Sam. "
                      "Who is the tallest?")
    assert "Tom is the tallest" in out


def test_relations_refuse_unrelated_pair():
    assert exact.solve("Tom is taller than Sam. Bo is taller than Ed. "
                       "Is Tom taller than Ed?") is None      # not entailed


def test_word_problems_are_computed_by_state_tracking():
    out = exact.solve("I have 3 apples and buy 4 more, then eat 2. "
                      "How many apples do I have now?")
    assert out.startswith("5")
    out2 = exact.solve("I had three apples and I bought four more. "
                       "How many apples do I have in total?")
    assert out2.startswith("7")                    # word numbers too


def test_word_problem_guards_ordinary_prose():
    assert exact.word_problem("I bought 4 apples yesterday.") is None
    assert exact.word_problem("how many people live in tokyo?") is None


def test_percent_change_is_computed():
    out = exact.solve("what is the percent increase from 50 to 75?")
    assert "50% increase" in out
    out2 = exact.solve("percent change from 80 to 60")
    assert "25% decrease" in out2
    assert exact.percent_change("percent increase from 0 to 5") is None


# ── exact text ops: the class frontier models famously fumble ─────────────────

def test_she_counts_letters_perfectly():
    out = exact.solve("how many r's are in strawberry?")
    assert "3" in out and "positions 3, 8, 9" in out
    # (the author of this test first wrote "2" here — SHE counted 3, and she
    # was right: c-h-e-e-s-e. The exact class beats approximation.)
    assert "3" in exact.solve("how many e's in cheese")


def test_letter_counts_spelling_reversal_nth():
    assert '"necessary" has 9 letters' in exact.solve(
        "how many letters in necessary?")
    assert '"drawer"' in exact.solve("spell drawer backwards") and \
        '"reward"' in exact.solve("spell drawer backwards")
    assert "N-E-C-E-S-S-A-R-Y" in exact.solve("how do you spell necessary?")
    assert "'y'" in exact.solve("what is the last letter of necessary?")


def test_list_ops_are_exact():
    assert "The largest is 9" in exact.solve("which is the largest: 3, 9, 4?")
    assert "The median is 5" in exact.solve("what is the median of 9, 1, 5?")
    assert "Sorted: 1, 3, 7" in exact.solve("sort 7, 1, 3")
    assert "Sorted: 7, 3, 1" in exact.solve("sort 7, 1, 3 in descending order")


# ── 2. the NativeMind: her notes are the model ────────────────────────────────

class _Knowledge:
    def __init__(self, entries):
        self._entries = entries

    def search_knowledge(self, query, k=5):
        return self._entries


def _note(title, content):
    return SimpleNamespace(id="k", title=title, content=content, confidence=0.7)


def test_native_answers_from_her_own_notes():
    mind = NativeMind(_Knowledge([_note(
        "photosynthesis",
        "Photosynthesis converts sunlight into sugar. Plants use chlorophyll "
        "to capture the light. The process releases oxygen.")]))
    brain = DeliberateReasoner(mind)
    ans = brain.reason("how does photosynthesis capture sunlight?")
    assert ans.ok and "chlorophyll" in ans.answer.lower()
    assert ans.confidence >= 0.55                 # coverage-backed, stands


def test_native_defers_when_her_notes_dont_cover_it():
    mind = NativeMind(_Knowledge([_note("pasta", "Boil pasta in salted water.")]))
    brain = DeliberateReasoner(mind)
    ans = brain.reason("explain quantum entanglement decoherence")
    assert (not ans.ok) or ans.confidence <= 0.35  # → the bridge escalates
    assert mind.deferrals >= 1


def test_native_never_writes_code_so_code_asks_defer():
    mind = NativeMind(_Knowledge([_note("python", "Python is a language.")]))
    brain = DeliberateReasoner(mind)
    ans = brain.reason("write a python function to sort a list")
    assert (not ans.ok) or ans.confidence <= 0.35


def test_native_decomposes_multipart_questions_natively():
    assert len(NativeMind(None).plan(
        "explain what RAM does and then explain what a CPU does")) == 2


def test_exact_tools_still_outrank_everything():
    mind = NativeMind(_Knowledge([_note("math", "Two plus two is five.")]))
    brain = DeliberateReasoner(mind)                # her note LIES about math
    assert brain.reason("what is 2 + 2?").answer == "2 + 2 = 4"


def test_build_reasoner_prefers_her_native_mind():
    brain = build_reasoner(knowledge=_Knowledge([]), ios=None)
    assert isinstance(brain.substrate, NativeMind)


# ── 3. routing: she answers BEFORE the cloud ──────────────────────────────────

class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _CloudSpy:
    def __init__(self):
        self.called = 0

    def available(self):
        return True

    def reason(self, q, *, context=None):
        self.called += 1
        return SimpleNamespace(ok=True, answer="cloud answer", model="x",
                               latency_ms=1.0)

    def status(self):
        return {}


class _IOS:
    def think(self, prompt, context=None, **kw):
        return SimpleNamespace(task="general", strategy="ios", ok=True,
                               confidence=0.7, answer="ios", models_used=[],
                               structured={}, trace_id="t", context_used={})


def test_her_mind_answers_before_the_cloud():
    cloud = _CloudSpy()
    brain = build_reasoner(knowledge=_Knowledge([]), ios=None)
    bridge = ConversationBridge(
        _IOS(), decision_log=_Log(), reasoner=cloud, local_reasoner=brain,
        speech=_SpeechOutput(synthesizer=lambda t: None))
    resp = bridge.think("All cats are animals. Sam is a cat. Is Sam an animal?")
    assert resp.answer.startswith("Yes")
    assert cloud.called == 0                       # SHE reasoned; no cloud
    assert "local_reasoner" in bridge._decision_log.rows[-1]["route"]


def test_uncovered_prose_still_reaches_the_cloud_teacher():
    cloud = _CloudSpy()
    brain = build_reasoner(knowledge=_Knowledge([]), ios=None)
    bridge = ConversationBridge(
        _IOS(), decision_log=_Log(), reasoner=cloud, local_reasoner=brain,
        speech=_SpeechOutput(synthesizer=lambda t: None))
    resp = bridge.think("summarize the history of the roman empire")
    assert resp.answer == "cloud answer"           # she deferred honestly
    assert cloud.called == 1
