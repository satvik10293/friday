"""
M31 — human-level listening: the transcript verifier.

Before FRIDAY thinks, she decides — like a person — whether a transcript was
meant for her and whether it was finished:
  · TV / ambient / other people      → IGNORE (not addressed)
  · unfinished thought               → WAIT (keep listening)
  · addressed + finished + heard well → ACCEPT
  · addressed + finished + heard badly → CLARIFY (ask, never guess)
And a natural follow-up after she answers does not need the wake word again.
"""

from __future__ import annotations

from core.audio.listener.verifier import (CompletenessDetector, ConversationState,
                                          TranscriptVerifier, VerdictAction)


# ── completeness (item 3) ─────────────────────────────────────────────────────

def test_finished_sentences_are_complete():
    det = CompletenessDetector()
    assert det.is_complete("what is the weather today")[0] is True
    assert det.is_complete("turn off the kitchen light")[0] is True


def test_trailing_connective_is_incomplete():
    det = CompletenessDetector()
    ok, reason = det.is_complete("can you open the")
    assert ok is False and reason == "dangling_word"
    assert det.is_complete("i want to")[0] is False


def test_filler_only_is_incomplete():
    det = CompletenessDetector()
    assert det.is_complete("um uh")[0] is False
    assert det.is_complete("")[0] is False


# ── address / background filter (items 4, 10) ─────────────────────────────────

def _verifier(**kw):
    return TranscriptVerifier(conversation=ConversationState(window_s=8.0), **kw)


def test_unaddressed_speech_is_ignored_as_background():
    v = _verifier(require_wake=True)
    verdict = v.verify("the stock market rose two percent today",
                       audio_confidence=0.9, wake_hit=False)
    assert verdict.action == VerdictAction.IGNORE
    assert verdict.reason == "not_addressed"


def test_wake_word_makes_it_addressed_and_accepted():
    v = _verifier(require_wake=True)
    verdict = v.verify("what time is it", audio_confidence=0.9, wake_hit=True)
    assert verdict.action == VerdictAction.ACCEPT
    assert verdict.confidence >= 0.9


def test_always_listening_mode_treats_everything_as_addressed():
    v = _verifier(require_wake=False)
    verdict = v.verify("what time is it", audio_confidence=0.9, wake_hit=False)
    assert verdict.action == VerdictAction.ACCEPT


# ── unfinished thought → wait, not answer ─────────────────────────────────────

def test_addressed_but_unfinished_waits():
    v = _verifier(require_wake=True)
    verdict = v.verify("remind me to", audio_confidence=0.9, wake_hit=True)
    assert verdict.action == VerdictAction.WAIT
    assert verdict.complete is False


def test_bare_wake_word_waits_for_the_command():
    v = _verifier(require_wake=True)
    verdict = v.verify("", audio_confidence=0.9, wake_hit=True)
    assert verdict.action == VerdictAction.WAIT
    assert verdict.reason == "awaiting_command"


# ── heard badly → clarify, never guess (items 7, 8) ───────────────────────────

def test_low_audio_confidence_asks_for_clarification():
    v = _verifier(require_wake=True, clarify_threshold=0.35)
    verdict = v.verify("open the garage door", audio_confidence=0.2, wake_hit=True)
    assert verdict.action == VerdictAction.CLARIFY
    assert verdict.reason == "low_audio_confidence"


# ── continuous conversation (item 9) ──────────────────────────────────────────

def test_follow_up_needs_no_wake_word_inside_the_window():
    v = _verifier(require_wake=True)
    v.verify("what's the weather", audio_confidence=0.9, wake_hit=True)   # opens window
    v.note_response("satvik")
    follow = v.verify("and tomorrow", audio_confidence=0.9, wake_hit=False)
    # "and tomorrow" trails on a connective -> WAIT, but crucially it was ADDRESSED
    assert follow.addressed is True
    real_follow = v.verify("what about tomorrow", audio_confidence=0.9, wake_hit=False)
    assert real_follow.action == VerdictAction.ACCEPT


def test_conversation_window_expires():
    conv = ConversationState(window_s=5.0)
    v = TranscriptVerifier(require_wake=True, conversation=conv)
    v.verify("hello there friend", audio_confidence=0.9, wake_hit=True, now=100.0)
    v.note_response("satvik", now=100.0)
    # 3s later still open, 10s later closed
    assert v.verify("what about tomorrow", audio_confidence=0.9,
                    wake_hit=False, now=103.0).addressed is True
    assert v.verify("what about tomorrow", audio_confidence=0.9,
                    wake_hit=False, now=110.0).action == VerdictAction.IGNORE


def test_a_different_speaker_does_not_hijack_the_window():
    conv = ConversationState(window_s=8.0)
    v = TranscriptVerifier(require_wake=True, conversation=conv)
    v.verify("hey there", audio_confidence=0.9, wake_hit=True, speaker="satvik",
             now=50.0)
    v.note_response("satvik", now=50.0)
    other = v.verify("pass the salt", audio_confidence=0.9, wake_hit=False,
                     speaker="guest", now=51.0)
    assert other.action == VerdictAction.IGNORE


# ── pipeline integration (opt-in, frame-driven) ───────────────────────────────

def test_pipeline_without_verifier_keeps_legacy_routing():
    from core.audio.listener.pipeline import ListeningPipeline
    p = ListeningPipeline(wake_required=False)
    assert p.verifier is None                       # additive: off by default


def test_service_can_enable_the_verifier():
    from core.audio.listener.service import ListeningService
    svc = ListeningService(wake_required=True, verify=True)
    assert svc.pipeline.verifier is not None
