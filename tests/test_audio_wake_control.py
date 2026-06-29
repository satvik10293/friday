"""M15 — Wake-word control + speech de-duplication: confidence gating, cooldown,
self-speech suppression, resume-after-speaking, duplicate rejection."""

import pytest

from core.audio.cognition.config import SpeechConfig, WakeConfig
from core.audio.cognition.dedup import SpeechDeduplicator
from core.audio.cognition.wake import WakeWordController
from core.audio.listener.wake_word import WakeWordEngine


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _controller(**cfg):
    clock = Clock()
    base = dict(wake_word="friday", wake_confidence=0.7, cooldown_s=2.0,
                self_speech_guard_s=0.5)
    base.update(cfg)
    return WakeWordController(WakeWordEngine(), WakeConfig(**base), clock=clock), clock


# ── wake detection ────────────────────────────────────────────────────────────────────
def test_wake_detects_and_strips():
    ctl, _ = _controller()
    res = ctl.detect("friday what time is it", audio_confidence=1.0)
    assert res.hit and res.word == "friday"
    assert ctl.strip_wake_word("friday what time is it") == "what time is it"


def test_wake_below_confidence_rejected():
    ctl, _ = _controller(wake_confidence=0.95)
    res = ctl.detect("friday hello", audio_confidence=0.2)   # low audio confidence
    assert not res.hit and res.reason == "below_threshold"


def test_wake_no_match():
    ctl, _ = _controller()
    res = ctl.detect("turn on the lights", audio_confidence=1.0)
    assert not res.hit and res.reason == "no_match"


def test_wake_cooldown_prevents_repeat():
    ctl, clock = _controller(cooldown_s=2.0)
    assert ctl.detect("friday one", audio_confidence=1.0).hit
    clock.advance(0.5)
    second = ctl.detect("friday two", audio_confidence=1.0)
    assert not second.hit and second.suppressed and second.reason == "cooldown"
    clock.advance(2.0)
    assert ctl.detect("friday three", audio_confidence=1.0).hit


# ── ignore FRIDAY's own speech + resume ────────────────────────────────────────────────
def test_self_speech_suppression_and_resume():
    ctl, clock = _controller(self_speech_guard_s=0.5)
    ctl.on_speaking_started()
    res = ctl.detect("friday stop", audio_confidence=1.0)
    assert res.suppressed and res.reason == "self_speech"
    assert not ctl.should_resume                       # still speaking
    ctl.on_speaking_finished()
    assert not ctl.should_resume                       # guard window still active
    clock.advance(0.6)
    assert ctl.should_resume                           # guard elapsed → resume
    assert ctl.detect("friday now", audio_confidence=1.0).hit


def test_wake_metrics():
    ctl, _ = _controller()
    ctl.detect("friday go", audio_confidence=1.0)
    m = ctl.metrics()
    assert m["activations"] == 1 and "friday" in m["words"]


# ── speech de-duplication ──────────────────────────────────────────────────────────────
def test_dedup_rejects_identical():
    clock = Clock()
    dd = SpeechDeduplicator(SpeechConfig(dedup_window_s=4.0), clock=clock)
    assert dd.check("turn on the lights").accepted
    dup = dd.check("turn on the lights")
    assert not dup.accepted and dup.similarity == 1.0


def test_dedup_allows_after_window():
    clock = Clock()
    dd = SpeechDeduplicator(SpeechConfig(dedup_window_s=4.0), clock=clock)
    dd.check("what is the weather")
    clock.advance(5.0)                                  # window elapsed
    assert dd.check("what is the weather").accepted


def test_dedup_allows_distinct():
    dd = SpeechDeduplicator(SpeechConfig())
    dd.check("play some music")
    assert dd.check("stop the music").accepted


def test_dedup_near_identical_rejected():
    dd = SpeechDeduplicator(SpeechConfig(dedup_similarity=0.9))
    dd.check("set a timer for ten minutes")
    res = dd.check("set a timer for ten minutes.")       # punctuation only
    assert not res.accepted


def test_dedup_ignores_too_short():
    dd = SpeechDeduplicator(SpeechConfig(min_partial_chars=3))
    assert not dd.check("a").accepted
