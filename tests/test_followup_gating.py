"""
Real-world fix: don't answer the TV.

Once the follow-up window is open, a wake-free turn used to be accepted at any
confidence, so background YouTube / ambient chatter (STT confidence ~0.5-0.6)
got answered — she replied to a video outro. A wake-free follow-up now needs a
higher confidence bar than a wake-word command, and a rejected/ambient turn
does NOT reopen the window (so noise can't hold the conversation open).
"""

from __future__ import annotations

from core.audio.listener.verifier import (ConversationState, TranscriptVerifier,
                                          VerdictAction)


def _verifier(**kw):
    return TranscriptVerifier(require_wake=True,
                              conversation=ConversationState(window_s=30.0),
                              follow_up_min_confidence=0.62, **kw)


def test_wake_word_command_accepts_at_modest_confidence():
    v = _verifier()
    verdict = v.verify("what is this game", audio_confidence=0.55, wake_hit=True)
    assert verdict.action == VerdictAction.ACCEPT      # wake word is proof


def test_weak_wake_free_followup_is_ignored_as_ambient():
    v = _verifier()
    v.verify("what is this game", audio_confidence=0.8, wake_hit=True)  # open window
    assert v.conversation.active()
    # a low-confidence wake-free turn (ambient TV) in the open window
    verdict = v.verify("leave a comment and see you next video",
                       audio_confidence=0.58, wake_hit=False)
    assert verdict.action == VerdictAction.IGNORE
    assert verdict.reason == "weak_followup"


def test_clear_wake_free_followup_still_accepted():
    v = _verifier()
    v.verify("what is this game", audio_confidence=0.8, wake_hit=True)
    verdict = v.verify("what is a game", audio_confidence=0.7, wake_hit=False)
    assert verdict.action == VerdictAction.ACCEPT      # genuine clear follow-up


def test_ambient_noise_does_not_hold_the_window_open():
    # an ignored weak follow-up must not reopen the window — otherwise a noisy
    # room keeps her listening forever
    v = _verifier()
    v.conversation.open("satvik", now=1000.0)          # window: 1000..1030
    v.verify("random tv chatter", audio_confidence=0.55, wake_hit=False,
             now=1005.0)
    # the window still expires at its original 1030, not extended by the noise
    assert not v.conversation.active(now=1031.0)
    assert v.conversation.active(now=1029.0)


def test_accepted_turn_reopens_the_window():
    v = _verifier()
    v.conversation.open("satvik", now=1000.0)
    v.verify("what is a game", audio_confidence=0.75, wake_hit=False, now=1005.0)
    # a genuine turn at t=1005 reopens the 30 s window → active well past 1030
    assert v.conversation.active(now=1034.0)
