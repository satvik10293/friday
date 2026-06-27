"""
core/audio/listener/silence_detector.py — FRIDAY 4.0 (M12.1)
Tracks silence to find pauses and sentence/command boundaries. Distinguishes a short
pause (within an utterance) from a long pause (end of command) by counting
consecutive non-speech frames — no fixed recording length.
"""

from __future__ import annotations

from .microphone import FRAME_MS


class SilenceState:
    NONE = "none"
    PAUSE = "pause"
    LONG_PAUSE = "long_pause"


class SilenceDetector:
    def __init__(self, *, pause_ms: int = 300, long_pause_ms: int = 800,
                 frame_ms: int = FRAME_MS) -> None:
        self._pause_frames = max(1, pause_ms // frame_ms)
        self._long_frames = max(1, long_pause_ms // frame_ms)
        self._silent = 0

    def update(self, is_speech: bool) -> str:
        if is_speech:
            self._silent = 0
            return SilenceState.NONE
        self._silent += 1
        if self._silent >= self._long_frames:
            return SilenceState.LONG_PAUSE
        if self._silent >= self._pause_frames:
            return SilenceState.PAUSE
        return SilenceState.NONE

    @property
    def silent_frames(self) -> int:
        return self._silent

    def reset(self) -> None:
        self._silent = 0
