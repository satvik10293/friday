"""
core/audio/listener/speaker.py — FRIDAY 4.0 (M12.1)
Local, cloud-free speaker recognition. Each enrolled voice is a small acoustic
fingerprint (energy, zero-crossing rate, spectral centroid + spread); identification
is nearest-fingerprint by cosine similarity. Distinguishes the primary user, known
users, guests, and unknown speakers — a foundation for multi-user support.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .microphone import SAMPLE_RATE


def fingerprint(audio: np.ndarray, sr: int = SAMPLE_RATE) -> np.ndarray:
    """A compact, deterministic voice fingerprint from spectral *shape* features
    (zero-crossing rate, spectral centroid, spread, and roll-off). Energy/volume is
    deliberately excluded — it describes loudness, not identity. Kept on a fixed
    scale so a distance metric is meaningful."""
    a = np.asarray(audio, dtype=np.float64)
    if a.size < 16:
        return np.zeros(4, dtype=np.float64)
    signs = np.signbit(a)
    zcr = float(np.mean(signs[1:] != signs[:-1]))
    mag = np.abs(np.fft.rfft(a * np.hanning(len(a))))
    freqs = np.fft.rfftfreq(len(a), 1 / sr)
    total = float(mag.sum()) + 1e-9
    centroid = float((mag * freqs).sum() / total)
    spread = float(np.sqrt(((freqs - centroid) ** 2 * mag).sum() / total))
    cum = np.cumsum(mag)
    rolloff_idx = int(np.searchsorted(cum, 0.85 * cum[-1]))
    rolloff = float(freqs[min(rolloff_idx, len(freqs) - 1)])
    return np.array([zcr, centroid / 4000.0, spread / 4000.0, rolloff / 4000.0])


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Euclidean-distance similarity in (0, 1] — identical voices → 1.0, different
    spectral shapes → low. Scale-aware (unlike cosine), so proportional tones don't
    collapse to 'identical'."""
    d = float(np.linalg.norm(a - b))
    return 1.0 / (1.0 + d)


@dataclass
class SpeakerResult:
    label: str = "unknown"
    confidence: float = 0.0
    known: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class SpeakerRecognizer:
    def __init__(self, *, primary: str = "satvik", threshold: float = 0.86) -> None:
        self.primary = primary
        self._threshold = threshold
        self._prints: dict[str, np.ndarray] = {}

    def enroll(self, label: str, audio: np.ndarray) -> None:
        fp = fingerprint(audio)
        if label in self._prints:
            self._prints[label] = (self._prints[label] + fp) / 2.0
        else:
            self._prints[label] = fp

    def identify(self, audio: np.ndarray) -> SpeakerResult:
        if not self._prints:
            return SpeakerResult("unknown", 0.0, False)
        fp = fingerprint(audio)
        best_label, best_sim = "unknown", 0.0
        for label, ref in self._prints.items():
            sim = _similarity(fp, ref)
            if sim > best_sim:
                best_label, best_sim = label, sim
        if best_sim >= self._threshold:
            return SpeakerResult(best_label, round(best_sim, 3), True)
        return SpeakerResult("unknown", round(best_sim, 3), False)

    def enrolled(self) -> list[str]:
        return list(self._prints)
