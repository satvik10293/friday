"""
core/audio/cognition/detector_base.py — FRIDAY V3 (M15)
The audio-event detector contract + a profile-based default detector.

A detector scores how strongly an analysis window matches one sound class, returning a
confidence in [0, 1]. Detectors are independent plugins: each declares the sound it
recognizes and (optionally) the backend it needs, reports `available()`, and NEVER
raises — a faulty/missing-backend detector scores 0 so it can never break the engine.

`ProfileDetector` is the always-available, model-free default: it scores a window
against a declarative `FeatureProfile` (per-feature target ranges + weights) using soft
trapezoidal membership. New sounds are added as data (a profile), not code — satisfying
"new sounds without modifying core logic". `MLEventDetector` is the seam where a learned
classifier (e.g. an AudioSet/YAMNet model) plugs in; absent a model it is unavailable.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Callable, Optional

from .features import AudioFeatures

log = logging.getLogger("friday.audio.detector")


@dataclass
class FeatureProfile:
    # ranges: feature_name -> (low|None, high|None, weight). Use None for an open bound.
    # Membership is 1 inside [low, high] and decays linearly to 0 across a margin =
    # max(span, |bound|*0.5) outside it.
    ranges: dict                     # feature_name -> (low|None, high|None, weight)

    def membership(self, features: AudioFeatures) -> float:
        fd = features.__dict__
        total_w = 0.0
        acc = 0.0
        for name, (low, high, weight) in self.ranges.items():
            v = float(fd.get(name, 0.0))
            m = _soft_membership(v, low, high)
            acc += weight * m
            total_w += weight
        return acc / total_w if total_w else 0.0


def _soft_membership(v: float, low: Optional[float], high: Optional[float]) -> float:
    lo = low if low is not None else -math.inf
    hi = high if high is not None else math.inf
    if lo <= v <= hi:
        return 1.0
    span = (hi - lo) if math.isfinite(hi) and math.isfinite(lo) else 0.0
    if v < lo:
        margin = max(span * 0.5, abs(lo) * 0.5, 1e-6)
        return max(0.0, 1.0 - (lo - v) / margin)
    margin = max(span * 0.5, abs(hi) * 0.5, 1e-6)
    return max(0.0, 1.0 - (v - hi) / margin)


class AudioEventDetector:
    """Base detector. Subclasses implement `_score(features) -> float`."""

    requires: tuple = ()

    def __init__(self, sound: str, category: str) -> None:
        self.sound = sound
        self.category = category
        self._available: Optional[bool] = None

    def available(self) -> bool:
        if self._available is None:
            import importlib.util
            self._available = all(importlib.util.find_spec(m) is not None
                                  for m in self.requires)
        return self._available

    def score(self, features: AudioFeatures) -> float:
        """Public entry — never raises; returns a confidence in [0, 1]."""
        if not self.available():
            return 0.0
        try:
            return max(0.0, min(1.0, float(self._score(features))))
        except Exception:  # noqa: BLE001 — a detector must never break the engine
            log.debug("detector %s failed", self.sound, exc_info=True)
            return 0.0

    def _score(self, features: AudioFeatures) -> float:  # pragma: no cover - overridden
        raise NotImplementedError


class ProfileDetector(AudioEventDetector):
    """Always-available detector that matches a window against a feature profile."""

    def __init__(self, sound: str, category: str, profile: FeatureProfile, *,
                 min_rms: float = 1e-3) -> None:
        super().__init__(sound, category)
        self.profile = profile
        self._min_rms = min_rms

    def _score(self, features: AudioFeatures) -> float:
        if features.rms < self._min_rms:
            return 0.0                          # silence is never an event
        return self.profile.membership(features)


class MLEventDetector(AudioEventDetector):
    """Hook for a learned multi-label classifier. Inject a callable that maps a window's
    features (or raw audio) to {sound: confidence}; absent a model it is unavailable."""

    def __init__(self, sound: str, category: str,
                 classifier: Optional[Callable[[AudioFeatures], dict]] = None) -> None:
        super().__init__(sound, category)
        self._classifier = classifier

    def set_classifier(self, classifier: Callable[[AudioFeatures], dict]) -> None:
        self._classifier = classifier
        self._available = None

    def available(self) -> bool:
        return self._classifier is not None

    def _score(self, features: AudioFeatures) -> float:
        scores = self._classifier(features) or {}
        return float(scores.get(self.sound, 0.0))
