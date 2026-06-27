"""
core/audio/listener/emotion.py — FRIDAY 4.0 (M12.1)
Local prosody-based emotion estimation. From energy level, energy variance, and
speaking rate (zero-crossing proxy) it estimates an emotional tone — calm, excited,
happy, stressed, urgent, neutral — which is passed as context into the M12
Intelligence Router so FRIDAY can respond appropriately.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .microphone import FRAME_SIZE


class Emotion(str):
    pass


_EMOTIONS = ("calm", "neutral", "happy", "excited", "stressed", "urgent")


@dataclass
class EmotionResult:
    emotion: str = "neutral"
    confidence: float = 0.0
    features: dict = None

    def to_dict(self) -> dict:
        return {"emotion": self.emotion, "confidence": self.confidence,
                "features": self.features or {}}


class EmotionEstimator:
    def estimate(self, audio: np.ndarray) -> EmotionResult:
        a = np.asarray(audio, dtype=np.float64)
        if a.size < FRAME_SIZE:
            return EmotionResult("neutral", 0.0, {})
        # frame-wise energy → level + variability (agitation)
        n = a.size // FRAME_SIZE
        frames = a[: n * FRAME_SIZE].reshape(n, FRAME_SIZE)
        energies = np.sqrt(np.mean(frames ** 2, axis=1))
        level = float(np.mean(energies))
        variability = float(np.std(energies))
        signs = np.signbit(a)
        rate = float(np.mean(signs[1:] != signs[:-1]))   # speaking-rate proxy

        features = {"level": round(level, 4), "variability": round(variability, 4),
                    "rate": round(rate, 4)}

        if level < 0.02:
            return EmotionResult("calm", 0.6, features)
        if variability > 0.06 and rate > 0.18:
            return EmotionResult("urgent", 0.6, features)
        if level > 0.12 and variability > 0.04:
            return EmotionResult("excited", 0.6, features)
        if variability > 0.05:
            return EmotionResult("stressed", 0.55, features)
        if level > 0.08:
            return EmotionResult("happy", 0.5, features)
        return EmotionResult("neutral", 0.5, features)

    def emotions(self) -> list[str]:
        return list(_EMOTIONS)
