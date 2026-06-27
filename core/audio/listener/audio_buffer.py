"""
core/audio/listener/audio_buffer.py — FRIDAY 4.0 (M12.1)
A rolling audio buffer that always holds the last few seconds of audio so speech is
never lost during processing. Pre-roll lets the segmenter recover clipped speech
(the words spoken just before VAD fired), and snapshots support replay + interruption
recovery. Bounded → constant memory over a 24-hour runtime.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Optional

import numpy as np

from .microphone import FRAME_SIZE, SAMPLE_RATE


class RollingBuffer:
    def __init__(self, seconds: float = 8.0, *, sample_rate: int = SAMPLE_RATE,
                 frame_size: int = FRAME_SIZE) -> None:
        self.sample_rate = sample_rate
        self.frame_size = frame_size
        self.capacity_frames = max(1, int(seconds * sample_rate / frame_size))
        self._frames: deque = deque(maxlen=self.capacity_frames)
        self._lock = threading.Lock()

    def append(self, frame: np.ndarray) -> None:
        with self._lock:
            self._frames.append(np.asarray(frame, dtype=np.float32))

    def snapshot(self) -> np.ndarray:
        """All buffered audio as one contiguous waveform (newest last)."""
        with self._lock:
            frames = list(self._frames)
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)

    def last(self, seconds: float) -> np.ndarray:
        """The most recent `seconds` of audio (for pre-roll / clipped-speech recovery)."""
        n = max(1, int(seconds * self.sample_rate / self.frame_size))
        with self._lock:
            frames = list(self._frames)[-n:]
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)

    def preroll_frames(self, count: int) -> list[np.ndarray]:
        with self._lock:
            return list(self._frames)[-count:] if count > 0 else []

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    @property
    def frames_held(self) -> int:
        return len(self._frames)

    @property
    def seconds_held(self) -> float:
        return round(self.frames_held * self.frame_size / self.sample_rate, 3)
