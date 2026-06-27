"""
core/audio/listener/speech_detector.py — FRIDAY 4.0 (M12.1)
Per-frame speech presence with hysteresis. Wraps the VAD and smooths its decision
over a short window so a single noisy/clipped frame neither starts nor ends speech
spuriously. Low latency: a decision per 20 ms frame.
"""

from __future__ import annotations

from collections import deque

import numpy as np

from .vad import AudioClass, VoiceActivityDetector


class SpeechDetector:
    def __init__(self, vad: VoiceActivityDetector | None = None, *,
                 start_frames: int = 2, end_frames: int = 8) -> None:
        self._vad = vad or VoiceActivityDetector()
        self._start = start_frames
        self._end = end_frames
        self._window: deque = deque(maxlen=max(start_frames, end_frames))
        self._active = False

    @property
    def active(self) -> bool:
        return self._active

    def process(self, frame: np.ndarray) -> tuple[bool, str, float]:
        """Return (speech_active, audio_class, confidence). Hysteresis prevents
        flicker: needs `start_frames` speech to begin, `end_frames` non-speech to end."""
        cls, conf = self._vad.classify(frame)
        self._window.append(cls == AudioClass.SPEECH.value)
        recent = list(self._window)
        if not self._active:
            if sum(recent[-self._start:]) >= self._start:
                self._active = True
        else:
            if len(recent) >= self._end and not any(recent[-self._end:]):
                self._active = False
        return self._active, cls, conf

    def reset(self) -> None:
        self._window.clear()
        self._active = False
