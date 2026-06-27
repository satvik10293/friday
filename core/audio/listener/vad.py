"""
core/audio/listener/vad.py — FRIDAY 4.0 (M12.1)
Voice Activity Detection + lightweight noise suppression. Classifies each frame as
speech / silence / noise (and flags music-like / non-speech energy) from RMS energy
and zero-crossing rate, with an adaptive noise floor so it tolerates fans, AC, and
background hum. Pure numpy → sub-millisecond per frame; no model required.
"""

from __future__ import annotations

from enum import Enum

import numpy as np


class AudioClass(str, Enum):
    SILENCE = "silence"
    SPEECH = "speech"
    NOISE = "noise"
    MUSIC = "music"


def rms(frame: np.ndarray) -> float:
    if frame.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))


def zero_crossing_rate(frame: np.ndarray) -> float:
    if frame.size < 2:
        return 0.0
    signs = np.signbit(frame)
    return float(np.mean(signs[1:] != signs[:-1]))


class NoiseSuppressor:
    """Gentle, real-time noise reduction: a vectorised high-pass (removes DC / low
    hum by subtracting a short moving average) plus a soft noise gate driven by the
    adaptive noise floor. Fully numpy → fast enough for every 20 ms frame."""

    def __init__(self, window: int = 16) -> None:
        self._window = window
        self.noise_floor = 1e-4

    def update_floor(self, frame_rms: float, is_silence: bool) -> None:
        if is_silence:
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * max(frame_rms, 1e-6)

    def process(self, frame: np.ndarray) -> np.ndarray:
        if frame.size == 0:
            return frame
        k = min(self._window, frame.size)
        kernel = np.ones(k, dtype=np.float32) / k
        low = np.convolve(frame, kernel, mode="same")    # low-frequency component
        out = (frame - low).astype(np.float32)            # high-pass: hum/DC removed
        # soft gate: attenuate frames sitting near the noise floor
        if rms(out) < self.noise_floor * 2.5:
            out = out * np.float32(0.4)
        return out


class VoiceActivityDetector:
    def __init__(self, *, energy_factor: float = 3.0, min_floor: float = 1e-4,
                 speech_zcr_max: float = 0.5) -> None:
        self._factor = energy_factor
        self.noise_floor = min_floor
        self._speech_zcr_max = speech_zcr_max
        self._adapt = 0.05

    def classify(self, frame: np.ndarray) -> tuple[str, float]:
        """Return (AudioClass, confidence 0..1)."""
        e = rms(frame)
        z = zero_crossing_rate(frame)
        threshold = self.noise_floor * self._factor

        if e < threshold:
            # adapt the floor toward quiet frames
            self.noise_floor = (1 - self._adapt) * self.noise_floor + self._adapt * max(e, 1e-6)
            return AudioClass.SILENCE.value, min(1.0, threshold / (e + 1e-9))

        ratio = e / (threshold + 1e-9)
        if z > self._speech_zcr_max:
            # loud but very high zero-crossings → broadband noise (keyboard, hiss)
            return AudioClass.NOISE.value, min(1.0, z)
        if z < 0.02 and ratio > 2.0:
            # loud, near-tonal, low ZCR → music/tone, not speech
            return AudioClass.MUSIC.value, min(1.0, ratio / 4.0)
        return AudioClass.SPEECH.value, min(1.0, 0.5 + 0.5 * min(1.0, ratio / 4.0))

    def is_speech(self, frame: np.ndarray) -> bool:
        return self.classify(frame)[0] == AudioClass.SPEECH.value
