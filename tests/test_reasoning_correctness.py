"""
Reasoning-brain correctness (M59.5): stop parroting, add conditional logic.

Live-use bug: with no cloud, her local brain RECITED stored sentences that
merely keyword-matched — including stored QUESTIONS and personal reminders:
  "capital of France?"  -> "what is the capital of Japan?"   (a stored question)
  "why is the sky blue"  -> "remember my favourite colour is blue" (a reminder)
  "first person on moon" -> "Tom is taller than Sam..."      (an unrelated note)
Fix: the extractive faculties keep only DECLARATIVE, on-topic sentences; when
nothing qualifies she defers honestly instead of parroting. Plus modus
ponens/tollens so "if P then Q; P; is Q?" is deduced, not guessed.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.intelligence.mini_brains import is_answer_sentence
from core.reasoning import exact
from core.reasoning.native import NativeMind


# ── the answer filter ─────────────────────────────────────────────────────────

def test_questions_and_reminders_are_not_answers():
    assert not is_answer_sentence("what is the capital of Japan?")
    assert not is_answer_sentence("who was the first person on the moon?")
    # STT drops the '?' — an interrogative LEAD word must still be caught
    assert not is_answer_sentence("what is the capital of Japan")
    assert not is_answer_sentence("who was the first person on the moon")
    assert not is_answer_sentence("remember that my favourite colour is blue")
    assert not is_answer_sentence("reminder: buy milk")
    assert not is_answer_sentence("study quantum computing")
    assert not is_answer_sentence("hi")                    # too short


def test_names_and_prose_starting_with_auxiliaries_survive():
    # the filter must not eat real prose that happens to start with a name/aux
    assert is_answer_sentence("Will Smith is an American actor")
    assert is_answer_sentence("Is a common English word, but this is prose")


def test_declarative_prose_is_an_answer():
    assert is_answer_sentence("Paris is the capital of France")
    assert is_answer_sentence("Photosynthesis converts sunlight into sugar")


# ── NativeMind no longer parrots ──────────────────────────────────────────────

class _Knowledge:
    def __init__(self, entries):
        self._entries = entries

    def search_knowledge(self, query, k=5):
        return self._entries


def _note(title, content):
    return SimpleNamespace(id="k", title=title, content=content, confidence=0.7)


def test_native_does_not_recite_a_stored_question():
    # her only "match" is a stored question about Japan — she must NOT parrot it
    mind = NativeMind(_Knowledge([
        _note("geo", "what is the capital of Japan? what is the capital of "
                     "Australia?")]))
    text, coverage = mind._extract("what is the capital of France")
    assert text == ""                                     # nothing recited
    assert coverage == 0.0                                # → she defers honestly


def test_native_does_not_recite_a_personal_reminder_off_topic():
    mind = NativeMind(_Knowledge([
        _note("me", "remember that my favourite colour is blue")]))
    text, _ = mind._extract("why is the sky blue")
    assert text == ""                                     # not parroted


def test_native_still_answers_from_real_prose():
    mind = NativeMind(_Knowledge([
        _note("sky", "The sky is blue because air scatters blue light more "
                     "than red light.")]))
    text, coverage = mind._extract("why is the sky blue")
    assert "scatters blue light" in text and coverage > 0.0


# ── conditional logic (modus ponens / tollens) ────────────────────────────────

def test_modus_ponens():
    out = exact.solve("If it is raining then the ground is wet. It is raining. "
                      "Is the ground wet?")
    assert out.startswith("Yes") and "wet" in out


def test_modus_tollens():
    out = exact.solve("If it is raining then the ground is wet. It is not wet. "
                      "Is it raining?")
    assert out.startswith("No")


def test_conditional_refuses_what_is_not_entailed():
    # affirming the consequent is NOT valid — she must not claim it
    out = exact.solve("If it is raining then the ground is wet. The ground is "
                      "wet. Is it raining?")
    assert out is None                                    # not entailed → defer


def test_disjunctive_syllogism():
    out = exact.solve("Either it is a cat or a dog. It is not a cat. Is it a dog?")
    assert out.startswith("Yes") and "dog" in out
    out2 = exact.solve("Either the door is open or closed. It is not open. "
                       "Is it closed?")
    assert out2.startswith("Yes") and "closed" in out2


def test_non_conditional_questions_are_left_alone():
    assert exact.solve("what is the capital of France?") is None
