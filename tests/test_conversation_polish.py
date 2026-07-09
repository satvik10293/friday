"""
M31 — conversation polish: perfect the loop that already works.

Every spoken reply is a real answer (no meta-narration, no question echo);
FRIDAY never answers her own TTS picked up by the mic; a noisy room gets one
clarification, not a nag loop; taught answers are stored answer-only as
knowledge so recalling them never replays the question.
"""

from __future__ import annotations

import time

from core.intelligence.builtin_models import (MemoryModel, PlanningModel,
                                              ReasonerModel,
                                              _strip_question_prefix)
from core.intelligence.base import InferenceRequest
from core.launcher.conversation import ConversationBridge, _SpeechOutput
from core.memory.learning_gate import LearningGate


# ── real answers, never narration ─────────────────────────────────────────────

def test_memory_model_speaks_the_recalled_content_not_a_count():
    request = InferenceRequest(
        prompt="what is my favourite colour?",
        context={"memories": [
            {"content": "remember that my favourite colour is blue"},
            {"content": "the weather was cold on Tuesday"}]})
    answer, _, confidence = MemoryModel()._run(request)
    assert "favourite colour is blue" in answer
    assert "Recalled" not in answer and "item" not in answer
    assert confidence > 0.4


def test_memory_model_admits_having_no_memories():
    answer, _, confidence = MemoryModel()._run(
        InferenceRequest(prompt="anything", context={}))
    assert "don't have any memories" in answer
    assert confidence <= 0.2


def test_planner_speaks_the_plan_not_a_step_count():
    answer, structured, _ = PlanningModel()._run(
        InferenceRequest(prompt="plan the garage cleanup project", context={}))
    assert answer.startswith("Here's my plan:")
    assert "steps." not in answer                    # no "Plan with N steps."
    assert structured["plan"]


def test_recalled_snippets_never_echo_the_stored_question():
    stored = ("what is the capital of Japan? The capital of Japan is Tokyo. "
              "It has been the capital since 1868.")
    assert _strip_question_prefix(stored).startswith("The capital of Japan")

    request = InferenceRequest(
        prompt="capital of Japan?",
        context={"memories": [{"content": stored}]})
    answer, _, _ = ReasonerModel()._run(request)
    assert not answer.lower().startswith("what is")
    assert "Tokyo" in answer


def test_strip_question_prefix_leaves_plain_statements_alone():
    assert _strip_question_prefix("Tokyo is the capital of Japan.") == \
        "Tokyo is the capital of Japan."


# ── taught answers are stored answer-only, as knowledge ───────────────────────

class _Memory:
    def __init__(self):
        self.calls = []

    def remember(self, who, content, **kw):
        self.calls.append((who, content, kw))
        return len(self.calls)


def test_teacher_answers_are_stored_answer_only_as_knowledge():
    gate = LearningGate()
    memory = _Memory()
    decision = gate.decide("what is the capital of Japan?",
                           "The capital of Japan is Tokyo.",
                           confidence=0.85, route=("chain_of_thought", "groq_teacher"))
    assert decision.reason == "taught" and decision.answer_only
    gate.apply(memory, decision, "what is the capital of Japan?",
               "The capital of Japan is Tokyo.")
    assert len(memory.calls) == 1                    # answer only, no question
    who, content, kw = memory.calls[0]
    assert who == "friday" and "Tokyo" in content
    assert kw["kind"] == "knowledge" and kw["tier"] == "semantic"


def test_ordinary_answers_still_store_the_full_exchange():
    gate = LearningGate()
    memory = _Memory()
    decision = gate.decide("how do solar panels degrade over time?",
                           "Panels lose roughly half a percent per year.",
                           confidence=0.8, route=("chain_of_thought",))
    gate.apply(memory, decision, "how do solar panels degrade over time?",
               "Panels lose roughly half a percent per year.")
    assert len(memory.calls) == 2                    # question + answer


# ── she never answers her own voice ───────────────────────────────────────────

class _Log:
    def __init__(self):
        self.rows = []

    def log(self, **row):
        self.rows.append(row)
        return len(self.rows)


class _IOS:
    def __init__(self, answer="The capital of Japan is Tokyo, since 1868."):
        self.calls = 0
        self._answer = answer

    def think(self, command, context=None, **kw):
        self.calls += 1

        class _R:
            ok = True
            task = "general"
            strategy = "direct"
            models_used = ["friday-reasoner"]
            trace_id = None
            confidence = 0.9
        _R.answer = self._answer
        return _R()


def _bridge(ios):
    return ConversationBridge(ios, decision_log=_Log(),
                              speech=_SpeechOutput(synthesizer=lambda t: None))


def test_her_own_speech_heard_back_is_dropped_silently():
    ios = _IOS()
    bridge = _bridge(ios)
    bridge.think("what is the capital of Japan?")    # she answers and speaks
    assert ios.calls == 1

    echo = bridge.think("the capital of japan is tokyo since 1868")
    assert ios.calls == 1                            # the brain was not asked
    assert echo.answer == ""
    assert bridge._decision_log.rows[-1]["route"] == ["self_echo"]
    assert bridge.status()["echoes_dropped"] == 1


def test_a_genuinely_new_command_is_not_mistaken_for_echo():
    ios = _IOS()
    bridge = _bridge(ios)
    bridge.think("what is the capital of Japan?")
    bridge.think("switch off the desk lamp please")
    assert ios.calls == 2


def test_echoes_fade_after_the_window():
    ios = _IOS()
    bridge = _bridge(ios)
    bridge.think("what is the capital of Japan?")
    bridge._recent_speech[0] = (bridge._recent_speech[0][0],
                                time.time() - 120)   # age the utterance
    bridge.think("the capital of japan is tokyo since 1868")
    assert ios.calls == 2                            # window expired -> real turn


# ── one clarification, not a nag loop ─────────────────────────────────────────

def test_repeated_noise_gets_one_clarification_then_silence():
    ios = _IOS()
    bridge = _bridge(ios)
    first = bridge.think("mumble", context={"audio_confidence": 0.1})
    assert "say it again" in first.answer.lower()

    second = bridge.think("rumble", context={"audio_confidence": 0.1})
    assert second.answer == ""                       # silent drop
    assert bridge._decision_log.rows[-1]["route"] == ["noise"]
    assert bridge.status()["clarifications"] == 1
    assert bridge.status()["noise_dropped"] == 1
    assert ios.calls == 0


def test_clarification_returns_after_the_cooldown():
    ios = _IOS()
    bridge = _bridge(ios)
    bridge.think("mumble", context={"audio_confidence": 0.1})
    bridge._last_clarify_ts -= 60                    # cooldown elapsed
    again = bridge.think("rumble", context={"audio_confidence": 0.1})
    assert "say it again" in again.answer.lower()
    assert bridge.status()["clarifications"] == 2
