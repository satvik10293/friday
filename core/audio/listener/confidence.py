"""
core/audio/listener/confidence.py — FRIDAY 4.0 (M12.1)
Audio confidence. Every transcription carries a composite confidence built from
signal quality (SNR), noise estimate, language confidence, wake-word confidence, and
the transcriber's own score. Surfaced to Mission Control.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_WEIGHTS = {"signal_quality": 0.30, "language": 0.15, "wake": 0.15, "transcription": 0.40}


@dataclass
class AudioConfidence:
    overall: float = 0.0
    signal_quality: float = 0.0
    noise_estimate: float = 0.0
    language_confidence: float = 0.0
    wake_confidence: float = 0.0
    transcription_confidence: float = 0.0

    @property
    def percent(self) -> int:
        return int(round(self.overall * 100))

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["percent"] = self.percent
        return d


class ConfidenceAnalyzer:
    def analyze(self, *, signal_rms: float, noise_floor: float,
                language_confidence: float = 0.0, wake_confidence: float = 0.0,
                transcription_confidence: float = 0.0) -> AudioConfidence:
        snr = signal_rms / (noise_floor + 1e-9)
        # map SNR (ratio) → 0..1 via a soft log curve
        signal_quality = max(0.0, min(1.0, math.log10(snr + 1) / 2.0)) if snr > 0 else 0.0
        overall = (_WEIGHTS["signal_quality"] * signal_quality
                   + _WEIGHTS["language"] * language_confidence
                   + _WEIGHTS["wake"] * wake_confidence
                   + _WEIGHTS["transcription"] * transcription_confidence)
        return AudioConfidence(
            overall=round(max(0.0, min(1.0, overall)), 4),
            signal_quality=round(signal_quality, 4),
            noise_estimate=round(noise_floor, 6),
            language_confidence=round(language_confidence, 4),
            wake_confidence=round(wake_confidence, 4),
            transcription_confidence=round(transcription_confidence, 4))
