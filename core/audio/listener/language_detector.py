"""
core/audio/listener/language_detector.py — FRIDAY 4.0 (M12.1)
Local language detection from a transcript — English / Telugu / Hindi (extensible).
Uses Unicode script ranges (no cloud, no model): Telugu and Devanagari (Hindi) have
distinct code blocks; otherwise Latin → English. Returns a confidence.
"""

from __future__ import annotations

from dataclasses import dataclass

_RANGES = {
    "te": (0x0C00, 0x0C7F),   # Telugu
    "hi": (0x0900, 0x097F),   # Devanagari (Hindi)
}


@dataclass
class LanguageResult:
    language: str = "en"
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class LanguageDetector:
    def __init__(self, *, default: str = "en") -> None:
        self._default = default

    def detect(self, text: str) -> LanguageResult:
        text = text or ""
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return LanguageResult(self._default, 0.0)
        counts = {lang: 0 for lang in _RANGES}
        latin = 0
        for c in letters:
            cp = ord(c)
            placed = False
            for lang, (lo, hi) in _RANGES.items():
                if lo <= cp <= hi:
                    counts[lang] += 1
                    placed = True
                    break
            if not placed and cp < 0x250:
                latin += 1
        total = len(letters)
        best_lang = max(counts, key=counts.get)
        if counts[best_lang] > 0:
            return LanguageResult(best_lang, round(counts[best_lang] / total, 3))
        return LanguageResult("en", round(latin / total, 3) if total else 0.0)

    def supported(self) -> list[str]:
        return ["en", *_RANGES.keys()]
