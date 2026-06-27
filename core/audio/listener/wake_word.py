"""
core/audio/listener/wake_word.py — FRIDAY 4.0 (M12.1)
Wake-word engine — deliberately independent of transcription (this module imports
nothing from transcription.py). It matches configured wake words (FRIDAY, Athena,
custom, multiple) and supports hot-swapping the active set at runtime. `detect_audio`
is the seam where a real on-audio keyword-spotting model plugs in; `detect` matches a
text hint for the always-listening path.
"""

from __future__ import annotations

import re
from typing import Optional

import numpy as np

_WORD = re.compile(r"[a-z0-9]+")
_DEFAULT = ("friday", "athena")


def _similar(a: str, b: str) -> float:
    """Cheap character-bigram similarity for near-miss matching ('fryday')."""
    if a == b:
        return 1.0
    ba = {a[i:i+2] for i in range(len(a) - 1)}
    bb = {b[i:i+2] for i in range(len(b) - 1)}
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


class WakeWordEngine:
    def __init__(self, words=None, *, threshold: float = 0.8) -> None:
        self._words = [w.lower() for w in (words or _DEFAULT)]
        self._threshold = threshold

    # ── hot-swappable vocabulary ────────────────────────────────────────────────
    def words(self) -> list[str]:
        return list(self._words)

    def add_word(self, word: str) -> None:
        w = word.lower().strip()
        if w and w not in self._words:
            self._words.append(w)

    def remove_word(self, word: str) -> bool:
        w = word.lower().strip()
        if w in self._words:
            self._words.remove(w)
            return True
        return False

    def set_words(self, words) -> None:
        self._words = [w.lower().strip() for w in words if w.strip()]

    # ── detection ───────────────────────────────────────────────────────────────
    def detect(self, text: str) -> tuple[bool, Optional[str], float]:
        """Detect a wake word in a text hint. Returns (hit, word, confidence)."""
        tokens = _WORD.findall((text or "").lower())
        best_word, best_score = None, 0.0
        for tok in tokens:
            for w in self._words:
                s = _similar(tok, w)
                if s > best_score:
                    best_word, best_score = w, s
        hit = best_score >= self._threshold
        return hit, (best_word if hit else None), round(best_score, 3)

    def detect_audio(self, audio: np.ndarray) -> tuple[bool, Optional[str], float]:
        """Seam for a real on-audio KWS model. The dependency-free default reports
        no detection (the text path is used until a model plugin is registered)."""
        return False, None, 0.0

    def strip_wake_word(self, text: str) -> str:
        """Remove the wake word prefix so the command is clean for the IOS."""
        tokens = (text or "").split()
        if tokens and any(_similar(tokens[0].lower().strip(".,!?"), w) >= self._threshold
                          for w in self._words):
            return " ".join(tokens[1:]).strip()
        return text
