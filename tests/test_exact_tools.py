"""
Exact truth tools (M54 perfection pass): the question classes where FRIDAY
genuinely competes with a frontier model — because she COMPUTES what a
language model approximates. Voice-first (spoken operators), units, dates,
comparisons; plus the engine's retrieval tool and code verify-repair loop.
"""

from __future__ import annotations

import datetime as dt

from core.reasoning import DeliberateReasoner, exact


# ── spoken math (what STT actually transcribes) ───────────────────────────────

def test_spoken_operators_are_computed():
    assert exact.solve("what is 48 times 12 plus 5") == "48 * 12 + 5 = 581"
    assert exact.solve("what is 100 divided by 4") == "100 / 4 = 25"
    assert exact.solve("what is 90 minus 37?") == "90 - 37 = 53"


def test_squared_and_power_words():
    assert exact.solve("what is 5 squared") == "5^2 = 25"
    assert exact.solve("what is 2 to the power of 10") == "2^10 = 1024"


def test_spoken_percent():
    assert exact.solve("what is 15 percent of 240") == "15% of 240 = 36"


def test_prose_with_numbers_is_not_solved():
    # "minus"/"times" guards: no calc intent → not arithmetic
    assert exact.solve("she was born in 1990 and moved in 1995") is None
    assert exact.solve("I met him 3 times last week") is None


# ── numbers spoken as words (STT does this) ───────────────────────────────────

def test_word_numbers_are_computed():
    assert exact.solve("what is forty eight times twelve") == "48 * 12 = 576"
    assert exact.solve("what is one hundred and five plus twenty") == \
        "105 + 20 = 125"
    assert exact.solve("what is two thousand minus three hundred") == \
        "2000 - 300 = 1700"


# ── inverse algebra: solve for the unknown ────────────────────────────────────

def test_solves_for_the_unknown():
    assert "The number is 7" in exact.solve("what number plus 5 makes 12")
    assert "The number is 7" in exact.solve("if x times 3 is 21, what is x?")
    assert "The number is 12" in exact.solve("20 minus what number is 8")
    assert "The number is 4" in exact.solve("5 times what number equals 20")


def test_division_by_zero_is_not_solved():
    assert exact.algebra("what number divided by 0 makes 5") is None


# ── aggregates ────────────────────────────────────────────────────────────────

def test_series_sum_is_exact():
    assert "5050" in exact.solve("what is the sum of the numbers from 1 to 100")


def test_average_is_computed():
    assert "is 6" in exact.solve("what is the average of 3, 5 and 10")


# ── units ─────────────────────────────────────────────────────────────────────

def test_unit_conversions_are_exact():
    assert exact.solve("convert 10 km to miles") == "10 km = 6.2137 mi"
    assert exact.solve("how many pounds is 5 kg") == "5 kg = 11.0231 lb"
    assert exact.solve("what is 100 celsius in fahrenheit") == "100 c = 212 f"
    assert exact.solve("convert 32 fahrenheit to celsius") == "32 f = 0 c"


def test_incompatible_units_are_not_guessed():
    assert exact.units("convert 10 km to kg") is None


# ── dates ─────────────────────────────────────────────────────────────────────

def test_days_between_dates():
    out = exact.solve("how many days between 2020-03-05 and 2020-06-01")
    assert out == "There are 88 days between 2020-03-05 and 2020-06-01."


def test_weekday_of_a_date():
    assert exact.solve("what day of the week is 2026-07-17") == \
        "2026-07-17 is a Friday."


def test_days_until_a_date():
    today = dt.date(2026, 7, 17)
    out = exact.dates("how many days until December 25", today=today)
    assert out == "There are 161 days until 2026-12-25."


def test_days_until_rolls_to_next_year_when_passed():
    today = dt.date(2026, 7, 17)
    out = exact.dates("how many days until March 1", today=today)
    assert "2027-03-01" in out


# ── comparisons: compute both sides ───────────────────────────────────────────

def test_comparison_computes_both_sides():
    out = exact.solve("which is bigger, 2 ** 10 or 999?")
    assert "1024" in out and "larger" in out
    out2 = exact.solve("which is smaller, 7 * 7 or 50?")
    assert "49" in out2 and "smaller" in out2


# ── the engine uses the whole toolbox ─────────────────────────────────────────

class _Sub:
    base_confidence = 0.5

    def __init__(self, replies=None, default=""):
        self._replies = replies or {}
        self._default = default
        self.prompts = []

    def available(self):
        return True

    def generate(self, prompt, *, context=None, temperature=0.3):
        self.prompts.append(prompt)
        for needle in sorted(self._replies, key=len, reverse=True):
            if needle.lower() in prompt.lower():
                return self._replies[needle]
        return self._default


def test_engine_answers_spoken_math_exactly():
    brain = DeliberateReasoner(_Sub(default="wrong"))
    ans = brain.reason("what is 48 times 12 plus 5")
    assert ans.answer == "48 * 12 + 5 = 581" and ans.confidence == 1.0


def test_engine_answers_units_and_dates_exactly():
    brain = DeliberateReasoner(_Sub(default="wrong"))
    assert brain.reason("convert 10 km to miles").confidence == 1.0
    assert brain.reason("what day of the week is 2026-07-17").answer.endswith(
        "Friday.")


# ── retrieval as a reasoning tool ─────────────────────────────────────────────

def test_recall_steps_read_her_notes_not_the_model():
    sub = _Sub(replies={
        "break the following question":
            "look up what photosynthesis is\nexplain how it powers plants",
        "using these steps": "It converts light to sugar, powering the plant.",
    }, default="model guess")
    notes = []

    def retriever(q):
        notes.append(q)
        return "Photosynthesis converts light into sugar."

    brain = DeliberateReasoner(sub, retriever=retriever)
    ans = brain.reason("explain how photosynthesis works and powers plants")
    assert ans.ok
    assert notes and "look up" in notes[0]           # the tool was consulted
    assert brain.recall_steps == 1


# ── code verify-repair ────────────────────────────────────────────────────────

def test_valid_code_is_verified_and_trusted():
    good = "def add(a, b):\n    return a + b"
    brain = DeliberateReasoner(_Sub(default=good))
    ans = brain.reason("write a python function to add two numbers")
    assert ans.ok and ans.answer == good
    assert ans.confidence >= 0.6                      # parses clean → trusted
    assert brain.code_checked == 1


def test_broken_code_gets_one_repair_pass():
    broken = "def add(a, b)\n    return a + b"        # missing colon
    fixed = "def add(a, b):\n    return a + b"

    class _RepairSub(_Sub):
        def generate(self, prompt, *, context=None, temperature=0.3):
            self.prompts.append(prompt)
            return fixed if "problems" in prompt else broken

    brain = DeliberateReasoner(_RepairSub())
    ans = brain.reason("write a python function to add two numbers")
    assert ans.answer == fixed
    assert brain.code_repaired == 1


def test_unrepairable_code_reports_low_confidence_so_it_defers():
    brain = DeliberateReasoner(_Sub(default="this is not python at all ((("))
    ans = brain.reason("write a python function to sort a list")
    assert ans.confidence <= 0.35                     # → the bridge escalates
