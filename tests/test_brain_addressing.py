"""
M46 — the brain society is user-addressable through the conversation bridge.

Name any brain and it answers for itself ("ask the vision brain what you
see"), aliases resolve ("hearing" → audio), the roster lists everyone, a
faulty brain answers gracefully, and none of it ever touches the cloud or the
local model team — brain answers come straight from the brain.
"""

from __future__ import annotations

from types import SimpleNamespace

from core.launcher.conversation import ConversationBridge, _SpeechOutput
from tests.test_cloud_reasoner import _FakeReasoner
from tests.test_teacher import _LocalIOS, _Log


class _FakeBrain:
    def __init__(self, summary="", fail=False):
        self.summary = summary
        self.fail = fail
        self.ticks = 0

    def tick(self):
        self.ticks += 1
        return SimpleNamespace(summary=self.summary) if self.summary else None

    def health(self):
        if self.fail:
            raise RuntimeError("sensor exploded")
        return {"status": "ok", "last_report": self.summary or None}

    def metrics(self):
        return {"ticks": self.ticks, "errors": 1 if self.fail else 0}


def _bridge(brains, ios=None, reasoner=None):
    return ConversationBridge(
        ios if ios is not None else _LocalIOS(confidence=0.9),
        decision_log=_Log(), reasoner=reasoner, brains=brains,
        speech=_SpeechOutput(synthesizer=lambda t: None), speak_answers=False)


def _society():
    return {"vision_brain": _FakeBrain("I see 2 objects: a laptop, a keyboard."),
            "audio_brain": _FakeBrain("I hear typing."),
            "memory_brain": _FakeBrain("Memory: 12 items (3 core).")}


def test_roster_lists_the_brains_without_touching_models():
    ios, reasoner = _LocalIOS(confidence=0.9), _FakeReasoner()
    bridge = _bridge(_society(), ios=ios, reasoner=reasoner)
    response = bridge.think("which brains do you have?")
    assert "3 brains online" in response.answer
    assert "vision" in response.answer and "audio" in response.answer
    assert bridge._decision_log.rows[0]["route"] == ["brain:roster"]
    assert reasoner.asked == [] and ios.thinks == 0


def test_a_named_brain_answers_for_itself():
    ios, reasoner = _LocalIOS(confidence=0.9), _FakeReasoner()
    bridge = _bridge(_society(), ios=ios, reasoner=reasoner)
    response = bridge.think("ask the vision brain what you see")
    assert response.answer == "I see 2 objects: a laptop, a keyboard."
    assert bridge._decision_log.rows[0]["route"] == ["brain:vision_brain"]
    assert reasoner.asked == [] and ios.thinks == 0


def test_aliases_resolve_to_the_right_brain():
    bridge = _bridge(_society())
    response = bridge.think("what does the hearing brain report?")
    assert response.answer == "I hear typing."
    assert bridge._decision_log.rows[0]["route"] == ["brain:audio_brain"]


def test_status_suffix_when_asked_for_health():
    bridge = _bridge(_society())
    response = bridge.think("memory brain status please")
    assert "Memory: 12 items" in response.answer
    assert "(status: ok" in response.answer and "ticks" in response.answer


def test_a_faulty_brain_still_answers_gracefully():
    bridge = _bridge({"vision_brain": _FakeBrain(fail=True)})
    response = bridge.think("ask the vision brain what you see")
    assert "degraded" in response.answer
    assert bridge._decision_log.rows[0]["route"] == ["brain:vision_brain"]


def test_an_offline_brain_says_so():
    bridge = _bridge(_society())
    response = bridge.think("ask the simulation brain for a forecast")
    assert "isn't online" in response.answer


def test_quiet_brain_reports_nothing_to_report():
    bridge = _bridge({"vision_brain": _FakeBrain(summary="")})
    response = bridge.think("vision brain, anything?")
    assert "nothing to report" in response.answer


def test_brainy_smalltalk_does_not_trigger_the_route():
    ios = _LocalIOS(confidence=0.9)
    bridge = _bridge(_society(), ios=ios)
    bridge.think("the weather is brainy today, isn't it")
    route = bridge._decision_log.rows[0]["route"]
    assert not any(str(r).startswith("brain:") for r in route)
    assert ios.thinks == 1                        # flowed to the normal path


# ── read-only route (security review) ─────────────────────────────────────────

def test_addressing_never_ticks_the_brain():
    """A voice command must not run brain side effects (memory promotion,
    consolidation) or publish guest-timed reports — the route is read-only."""
    society = _society()
    bridge = _bridge(society)
    bridge.think("ask the memory brain what it holds")
    assert society["memory_brain"].ticks == 0


def test_brain_answers_stay_out_of_the_cloud_context():
    """Brain answers carry unmarked sensor state; they must never enter the
    conversation window that rides to the cloud in recent_turns."""
    reasoner = _FakeReasoner()
    bridge = _bridge(_society(), reasoner=reasoner)
    bridge.think("ask the vision brain what you see")
    bridge.think("what is the capital of Australia?")   # cloud turn
    turns = " ".join(t.get("text", "")
                     for t in reasoner.contexts[-1]["recent_turns"])
    assert "laptop" not in turns and "vision brain" not in turns
