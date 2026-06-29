"""
core/audio/cognition/dedup.py — FRIDAY V3 (M15)
Speech de-duplication. Continuous recognition (and overlapping partial segments) can
report the same sentence twice; routing it twice means FRIDAY answers twice. The
deduplicator remembers recently accepted transcripts and rejects a new one that is
identical or near-identical within a short time window — while still allowing genuine
repetition after the window, and partial sentences that are real new content.

Pure logic + clock; normalized comparison with a configurable similarity threshold.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable, Optional

from .config import SpeechConfig

_NORM = re.compile(r"[^a-z0-9 ]+")


def _normalize(text: str) -> str:
    return _NORM.sub("", (text or "").lower()).strip()


@dataclass
class DedupResult:
    accepted: bool
    duplicate_of: Optional[str] = None
    similarity: float = 0.0


class SpeechDeduplicator:
    def __init__(self, config: Optional[SpeechConfig] = None, *,
                 clock: Callable[[], float] = time.time) -> None:
        self.config = config or SpeechConfig()
        self._clock = clock
        self._recent: deque = deque(maxlen=64)     # (normalized_text, ts)
        self._duplicates = 0
        self._accepted = 0

    def check(self, text: str) -> DedupResult:
        """Return whether `text` is new (accepted) or a recent duplicate. Accepted
        transcripts are remembered; duplicates are not re-added."""
        norm = _normalize(text)
        now = self._clock()
        self._evict(now)
        if len(norm) < self.config.min_partial_chars:
            return DedupResult(False, similarity=0.0)   # too short to be a real command

        best_text, best_sim = None, 0.0
        for prev_norm, _ts in self._recent:
            sim = SequenceMatcher(None, norm, prev_norm).ratio()
            if sim > best_sim:
                best_text, best_sim = prev_norm, sim
        if best_sim >= self.config.dedup_similarity:
            self._duplicates += 1
            return DedupResult(False, duplicate_of=best_text, similarity=round(best_sim, 4))

        self._recent.append((norm, now))
        self._accepted += 1
        return DedupResult(True, similarity=round(best_sim, 4))

    def _evict(self, now: float) -> None:
        window = self.config.dedup_window_s
        while self._recent and now - self._recent[0][1] > window:
            self._recent.popleft()

    def reset(self) -> None:
        self._recent.clear()

    def metrics(self) -> dict:
        return {"accepted": self._accepted, "duplicates": self._duplicates,
                "tracked": len(self._recent)}
