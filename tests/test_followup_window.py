"""
Real-world fix: hands-free follow-up must survive her own (slow) reply.

The follow-up window used to be timed from when the answer was COMPUTED, so on
a slow CPU her multi-second spoken reply ate most of an 8 s window and the user
had to say 'Friday' every single turn. Now the bridge reopens the window when
she FINISHES speaking, so the reply clock starts from her last word.
"""

from __future__ import annotations

import time

from core.audio.listener.verifier import ConversationState
from core.launcher.conversation import ConversationBridge, _SpeechOutput
from tests.test_teacher import _LocalIOS, _Log


def _bridge(state, synth):
    speech = _SpeechOutput(synthesizer=synth)
    return ConversationBridge(
        _LocalIOS(confidence=0.9), decision_log=_Log(),
        conversation_state=state, speech=speech, speak_answers=True)


def test_window_reopens_after_she_finishes_speaking():
    state = ConversationState(window_s=5.0)
    done = []
    bridge = _bridge(state, synth=lambda s: done.append(s))
    assert not state.active()
    bridge._say("This is a fairly long spoken answer.")
    # wait for the async speech worker to finish the utterance
    deadline = time.time() + 3.0
    while not done and time.time() < deadline:
        time.sleep(0.02)
    time.sleep(0.05)
    assert done, "speech never completed"
    assert state.active(), "window did not reopen after she finished speaking"


def test_no_conversation_state_is_harmless():
    # a bridge with no window wired (tests/headless) must not crash on speech
    done = []
    bridge = ConversationBridge(
        _LocalIOS(confidence=0.9), decision_log=_Log(),
        speech=_SpeechOutput(synthesizer=lambda s: done.append(s)),
        speak_answers=True)
    bridge._say("hello")
    deadline = time.time() + 3.0
    while not done and time.time() < deadline:
        time.sleep(0.02)
    assert done


def test_reopen_is_measured_from_her_last_word():
    # the window opened at answer time would already be near-empty after a long
    # reply; reopening on completion gives the user the full window afterwards
    state = ConversationState(window_s=10.0)
    done = []

    def slow_synth(sentence):
        time.sleep(0.15)                     # stand in for slow CPU TTS
        done.append(sentence)

    bridge = _bridge(state, synth=slow_synth)
    bridge._say("One. Two. Three.")          # three sentences, ~0.45 s of speech
    deadline = time.time() + 3.0
    while len(done) < 3 and time.time() < deadline:
        time.sleep(0.02)
    reopened_at = state._active_until
    # the window's expiry is anchored after speech finished, i.e. into the future
    assert reopened_at > time.time() + 9.0, \
        "window was not reopened from her last word"
