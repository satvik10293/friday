"""
core/audio/listener/speech_segmenter.py — FRIDAY 4.0 (M12.1)
Turns the frame stream into utterance segments with dynamic boundaries — speech
start, pauses, long-pause (= command end), and back-to-back commands — with no fixed
recording length. A short pre-roll of frames captured before speech onset is
prepended so the first word is never clipped.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .microphone import FRAME_SIZE, SAMPLE_RATE
from .silence_detector import SilenceDetector, SilenceState
from .speech_detector import SpeechDetector


@dataclass
class Segment:
    audio: np.ndarray
    start_ts: float
    end_ts: float
    frames: int = 0

    @property
    def duration_s(self) -> float:
        return round(len(self.audio) / SAMPLE_RATE, 3)

    def summary(self) -> dict:
        return {"duration_s": self.duration_s, "frames": self.frames,
                "start_ts": self.start_ts, "end_ts": self.end_ts}


class SpeechSegmenter:
    def __init__(self, *, detector: Optional[SpeechDetector] = None,
                 silence: Optional[SilenceDetector] = None,
                 preroll_frames: int = 8, max_segment_s: float = 20.0) -> None:
        self._detector = detector or SpeechDetector()
        self._silence = silence or SilenceDetector()
        self._preroll: deque = deque(maxlen=preroll_frames)
        self._collecting = False
        self._frames: list[np.ndarray] = []
        self._start_ts = 0.0
        self._max_frames = int(max_segment_s * SAMPLE_RATE / FRAME_SIZE)
        self.boundary = SilenceState.NONE     # last boundary observed

    @property
    def collecting(self) -> bool:
        return self._collecting

    def process(self, frame: np.ndarray, *, ts: Optional[float] = None
                ) -> Optional[Segment]:
        """Feed one frame. Returns a finished Segment at a command boundary, else None."""
        ts = ts if ts is not None else time.time()
        is_speech, _cls, _conf = self._detector.process(frame)

        if not self._collecting:
            self._preroll.append(np.asarray(frame, dtype=np.float32))
            if is_speech:
                # begin a segment, prepending the pre-roll (clipped-speech recovery)
                self._collecting = True
                self._frames = list(self._preroll)
                self._start_ts = ts
                self._silence.reset()
            return None

        self._frames.append(np.asarray(frame, dtype=np.float32))
        state = self._silence.update(is_speech)
        self.boundary = state

        if state == SilenceState.LONG_PAUSE or len(self._frames) >= self._max_frames:
            return self._finish(ts)
        return None

    def _finish(self, ts: float) -> Segment:
        audio = (np.concatenate(self._frames) if self._frames
                 else np.zeros(0, dtype=np.float32))
        seg = Segment(audio=audio, start_ts=self._start_ts, end_ts=ts,
                      frames=len(self._frames))
        self._collecting = False
        self._frames = []
        self._detector.reset()
        self._silence.reset()
        self._preroll.clear()
        return seg

    def flush(self) -> Optional[Segment]:
        """Force-close any in-progress segment (e.g. on stop/interruption)."""
        if self._collecting and self._frames:
            return self._finish(time.time())
        return None
