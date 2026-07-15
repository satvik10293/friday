"""
core/audio/listener/verifier.py — FRIDAY 5.x (M31, human-level listening)
The Transcript Verifier: the seam between hearing and thinking. A raw transcript
is never handed straight to cognition — first FRIDAY decides, the way a person
does, *whether someone was actually talking to her and whether they finished*:

    Was that meant for me?   (address / background filter — items 4, 10)
    Did they finish?         (sentence completeness — item 3)
    Did I hear it well?      (audio confidence — items 2, 7, 8)

The output is a single Verdict with an action and a human-readable reason:

    ACCEPT  → route to cognition
    WAIT    → addressed but the thought is unfinished; keep listening
    CLARIFY → addressed and finished but heard poorly; ask, don't guess
    IGNORE  → not for her (TV, ambient speech, other people) or empty

Pure Python, no numpy, <1 ms — additive to the existing pipeline and fully
testable without hardware. It carries the "only enter conversation when the
user is addressing FRIDAY" rule, plus a continuous-conversation window so a
natural follow-up does not need the wake word again (item 9).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

_WORD = re.compile(r"[a-z']+")

# fillers / hesitation — a turn made only of these is a thinking pause, not speech
_FILLER = {"um", "uh", "er", "erm", "hmm", "mm", "mmm", "uhh", "ah", "eh", "hm"}

# ending on one of these strongly signals the speaker is mid-thought (item 3).
# Deliberately excludes pronouns/copulas/demonstratives — "what time is it",
# "who is it", "what is that" are complete questions that end on those words.
_DANGLING = {
    "and", "but", "or", "so", "because", "if", "when", "while", "the", "a", "an",
    "to", "of", "for", "with", "my", "your", "his", "her", "their", "our",
    "into", "onto",
}


class VerdictAction(str, Enum):
    ACCEPT = "accept"
    WAIT = "wait"
    CLARIFY = "clarify"
    IGNORE = "ignore"


@dataclass
class Verdict:
    action: VerdictAction
    reason: str
    confidence: float = 0.0
    complete: bool = True
    addressed: bool = True

    @property
    def route(self) -> bool:
        return self.action == VerdictAction.ACCEPT

    def to_dict(self) -> dict:
        return {"action": self.action.value, "reason": self.reason,
                "confidence": round(self.confidence, 3), "complete": self.complete,
                "addressed": self.addressed}


def _content_words(text: str) -> list[str]:
    return [t for t in _WORD.findall((text or "").lower())
            if len(t) >= 2 and t not in _FILLER]


class CompletenessDetector:
    """Cheap grammar-shape check for 'did they finish the thought?' (item 3).
    Conservative by design — it should catch obvious trailing-off, not force
    FRIDAY to wait forever on terse commands."""

    def __init__(self, *, min_words: int = 1) -> None:
        self.min_words = min_words

    def is_complete(self, text: str) -> tuple[bool, str]:
        words = _content_words(text)
        if len(words) < self.min_words:
            return False, "too_few_words"
        raw = _WORD.findall((text or "").lower())
        if raw and raw[-1] in _DANGLING:
            return False, "dangling_word"          # "...can you open the"
        if all(w in _FILLER for w in raw):
            return False, "filler_only"            # "um, uh"
        return True, "complete"


class ConversationState:
    """A short window after FRIDAY speaks during which the same speaker may
    continue without repeating the wake word (item 9). Expires on inactivity."""

    def __init__(self, *, window_s: float = 8.0) -> None:
        self.window_s = window_s
        self._active_until = 0.0
        self.speaker: Optional[str] = None

    def open(self, speaker: Optional[str] = None, *, now: Optional[float] = None) -> None:
        self._active_until = (now if now is not None else time.time()) + self.window_s
        if speaker is not None:
            self.speaker = speaker

    def active(self, *, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) < self._active_until

    def close(self) -> None:
        self._active_until = 0.0
        self.speaker = None


class TranscriptVerifier:
    """Turns a transcript + signals into a single routing verdict. `require_wake`
    mirrors the pipeline's policy: when False (always-listening demo mode) every
    finished utterance is treated as addressed; when True, only a wake word or an
    open conversation window counts as 'talking to FRIDAY'."""

    def __init__(self, *, require_wake: bool = True,
                 clarify_threshold: float = 0.35,
                 follow_up_min_confidence: float = 0.62,
                 conversation: Optional[ConversationState] = None,
                 completeness: Optional[CompletenessDetector] = None,
                 require_known_speaker: bool = False) -> None:
        self.require_wake = require_wake
        self.clarify_threshold = clarify_threshold
        # a wake-free follow-up (relying on the open window, no wake word) must
        # clear a HIGHER bar than a wake-word command: the wake word is proof
        # she's addressed, but ambient TV / background chatter in the window is
        # not. Without this she answers a YouTube outro or a distant
        # conversation the moment the window is open.
        self.follow_up_min_confidence = follow_up_min_confidence
        self.require_known_speaker = require_known_speaker
        self.conversation = conversation or ConversationState()
        self.completeness = completeness or CompletenessDetector()

    def _addressed(self, wake_hit: bool, speaker: Optional[str],
                   speaker_known: bool, now: Optional[float]) -> bool:
        if not self.require_wake:
            return True
        if wake_hit:
            return True
        if not self.conversation.active(now=now):
            return False
        if self.require_known_speaker and not speaker_known:
            return False
        # a follow-up must come from the speaker FRIDAY was just talking to
        if self.conversation.speaker not in (None, "unknown") and speaker not in (
                None, "unknown") and speaker != self.conversation.speaker:
            return False
        return True

    def verify(self, command: str, *, audio_confidence: float = 1.0,
               wake_hit: bool = False, speaker: Optional[str] = None,
               speaker_known: bool = False, now: Optional[float] = None) -> Verdict:
        addressed = self._addressed(wake_hit, speaker, speaker_known, now)
        if not addressed:
            # TV, ambient speech, or two other people talking — not for her
            return Verdict(VerdictAction.IGNORE, "not_addressed", 0.0,
                           complete=True, addressed=False)

        words = _content_words(command)
        if not words:
            # "Friday?" alone opens the window and waits; a wake-free empty
            # blip is just noise — neither reopens the window
            if wake_hit:
                self.conversation.open(speaker, now=now)
                return Verdict(VerdictAction.WAIT, "awaiting_command", 0.0,
                               complete=False, addressed=True)
            return Verdict(VerdictAction.IGNORE, "empty", 0.0,
                           complete=False, addressed=True)

        # a wake-free follow-up must clear a higher STT bar — otherwise ambient
        # TV / background chatter in the open window gets answered. Ignored
        # silently (no nag) and does NOT reopen the window, so ambient noise
        # can't hold the conversation open indefinitely.
        if not wake_hit and audio_confidence < self.follow_up_min_confidence:
            return Verdict(VerdictAction.IGNORE, "weak_followup",
                           audio_confidence, complete=True, addressed=True)

        complete, creason = self.completeness.is_complete(command)
        if not complete:
            self.conversation.open(speaker, now=now)   # keep listening for the rest
            return Verdict(VerdictAction.WAIT, creason, audio_confidence,
                           complete=False, addressed=True)

        if audio_confidence < self.clarify_threshold:
            return Verdict(VerdictAction.CLARIFY, "low_audio_confidence",
                           audio_confidence, complete=True, addressed=True)

        # accept — a genuine turn; (re)open the window for the next follow-up
        self.conversation.open(speaker, now=now)
        conf = audio_confidence
        if wake_hit:
            conf = min(1.0, conf + 0.05)
        if speaker_known:
            conf = min(1.0, conf + 0.05)
        return Verdict(VerdictAction.ACCEPT, "accepted", round(conf, 3),
                       complete=True, addressed=True)

    def note_response(self, speaker: Optional[str] = None, *,
                      now: Optional[float] = None) -> None:
        """Call after FRIDAY answers, to (re)open the follow-up window."""
        self.conversation.open(speaker, now=now)
