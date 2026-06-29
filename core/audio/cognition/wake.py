"""
core/audio/cognition/wake.py — FRIDAY V3 (M15)
Wake-word control on top of the M12.1 `WakeWordEngine`. The engine matches words; this
controller adds the *behaviour* a real assistant needs and that the milestone requires:

  • Ignore FRIDAY's own synthesized speech (barge-in suppression while/just after TTS).
  • Confidence-based detection (configurable threshold, no hardcoded value).
  • Prevent repeated triggers (cooldown after a successful activation).
  • Resume listening automatically once speaking ends (with a short guard window).

It wraps the engine additively (composition) — the M12.1 engine is untouched and still
usable on its own. Pure logic + clock; trivially testable with an injected time source.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from .config import WakeConfig


@dataclass
class WakeResult:
    hit: bool
    word: Optional[str]
    confidence: float
    suppressed: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class WakeWordController:
    def __init__(self, engine, config: Optional[WakeConfig] = None, *,
                 clock: Callable[[], float] = time.time) -> None:
        self._engine = engine
        self.config = config or WakeConfig()
        self._clock = clock
        # apply configured vocabulary additively
        if self.config.wake_word:
            self._engine.set_words([self.config.wake_word, *self.config.extra_words])
        self._speaking = False
        self._spoke_until = 0.0          # guard window after TTS ends
        self._last_wake = 0.0
        self._activations = 0
        self._suppressions = 0

    # ── own-speech awareness (ignore FRIDAY's TTS) ───────────────────────────────
    def on_speaking_started(self) -> None:
        """Call when FRIDAY begins speaking — wake detection is suppressed."""
        self._speaking = True

    def on_speaking_finished(self) -> None:
        """Call when FRIDAY stops speaking — start the post-speech guard, then resume."""
        self._speaking = False
        self._spoke_until = self._clock() + self.config.self_speech_guard_s

    @property
    def listening_suppressed(self) -> bool:
        return self._speaking or self._clock() < self._spoke_until

    @property
    def should_resume(self) -> bool:
        """True once it is safe to resume reacting to wake words after speaking."""
        return self.config.resume_after_speaking and not self.listening_suppressed

    # ── detection ────────────────────────────────────────────────────────────────
    def detect(self, text: str, *, audio_confidence: float = 1.0) -> WakeResult:
        """Confidence-gated, cooldown-guarded, self-speech-aware wake detection."""
        now = self._clock()
        hit, word, conf = self._engine.detect(text or "")
        # blend the word-match confidence with the upstream audio confidence
        confidence = round(conf * (0.5 + 0.5 * float(audio_confidence)), 4)

        if not hit or confidence < self.config.wake_confidence:
            return WakeResult(False, None, confidence, reason="below_threshold" if hit else "no_match")

        if self.listening_suppressed:
            self._suppressions += 1
            return WakeResult(False, word, confidence, suppressed=True, reason="self_speech")

        if now - self._last_wake < self.config.cooldown_s:
            self._suppressions += 1
            return WakeResult(False, word, confidence, suppressed=True, reason="cooldown")

        self._last_wake = now
        self._activations += 1
        return WakeResult(True, word, confidence, reason="activated")

    def strip_wake_word(self, text: str) -> str:
        return self._engine.strip_wake_word(text)

    # ── observability ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"activations": self._activations, "suppressions": self._suppressions,
                "speaking": self._speaking, "words": self._engine.words(),
                "threshold": self.config.wake_confidence}
