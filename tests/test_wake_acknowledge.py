"""
Real-world fix: 'Friday?' alone must get an answer, not silence.

The wake word with no command used to be discarded (empty command → not
routed → nothing spoken), so the user who just says her name got no reply and
no open follow-up window. Now she acknowledges ("Yes?") and holds the window
so the next words route without re-waking. Every heard segment also leaves a
truthful trace so "heard nothing" and "heard, chose not to answer" are
distinguishable.
"""

from __future__ import annotations

import logging

import numpy as np

from core.audio.listener.microphone import ArraySource, silence, tone
from core.audio.listener.pipeline import ListeningPipeline
from core.audio.listener.transcription import FakeTranscriber
from core.audio.listener.verifier import ConversationState, TranscriptVerifier


class _AckIOS:
    def __init__(self):
        self.acked = []
        self.commands = []

    def wake_acknowledge(self, speaker=""):
        self.acked.append(speaker)

    def think(self, prompt, context=None):
        self.commands.append(prompt)
        class R:
            def to_dict(self_): return {"answer": "ok"}
        return R()


def _command_wav():
    return np.concatenate([silence(0.2), tone(0.5, 300, 0.3), silence(1.0)])


def _pipe(script, ios):
    return ListeningPipeline(
        microphone=ArraySource(_command_wav()),
        transcriber=FakeTranscriber(script=script), intelligence_os=ios,
        verifier=TranscriptVerifier(require_wake=True,
                                    conversation=ConversationState(window_s=8.0)),
        wake_required=True)


def test_wake_word_alone_is_acknowledged_not_ignored():
    ios = _AckIOS()
    p = _pipe(["friday"], ios)
    p.pump()
    assert ios.acked, "saying just 'Friday' produced no acknowledgment"
    assert ios.commands == [], "an empty command should not reach cognition"


def test_wake_word_opens_the_follow_up_window():
    # after 'Friday?' alone the conversation window must be OPEN, so the next
    # words route without a second wake word (the verifier's own end-to-end
    # routing is covered in test_transcript_verifier; here we pin the contract
    # that the wake-only path leaves the window active)
    ios = _AckIOS()
    verifier = TranscriptVerifier(require_wake=True,
                                  conversation=ConversationState(window_s=8.0))
    assert not verifier.conversation.active()
    p = _pipe(["friday"], ios)
    p.verifier = verifier
    p.pump()
    assert ios.acked
    assert verifier.conversation.active(), \
        "wake word alone did not open the follow-up window"


def test_every_heard_segment_leaves_a_trace(caplog):
    ios = _AckIOS()
    p = _pipe(["not for her at all"], ios)     # no wake word → ignored
    with caplog.at_level(logging.INFO, logger="friday.audio.pipeline"):
        p.pump()
    traces = [r.message for r in caplog.records if "heard" in r.message]
    assert traces, "an ignored utterance left no diagnostic trace"
    # the trace shows what she heard, the confidence, and why she stayed quiet
    joined = " ".join(traces)
    assert "not for her at all" in joined and "wake=False" in joined
    assert ios.commands == []
