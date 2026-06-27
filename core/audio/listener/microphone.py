"""
core/audio/listener/microphone.py — FRIDAY 4.0 (M12.1)
Microphone abstraction. The pipeline reads fixed-size frames of mono float32 audio
from a `MicrophoneSource`. `ArraySource` feeds pre-recorded/synthetic audio (the
test + offline source); `LiveMicrophone` wraps sounddevice when present. The mic can
be disabled instantly (privacy) — a disabled mic returns silence, never blocks.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Optional

import numpy as np

log = logging.getLogger("friday.audio.microphone")

SAMPLE_RATE = 16000
FRAME_MS = 20
FRAME_SIZE = SAMPLE_RATE * FRAME_MS // 1000      # 320 samples / 20 ms


class MicrophoneSource:
    """Base mic: frame-based, instantly disable-able (privacy)."""

    sample_rate = SAMPLE_RATE
    frame_size = FRAME_SIZE

    def __init__(self) -> None:
        self._enabled = True
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        """Privacy: stop capturing immediately; reads return silence."""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _silence(self) -> np.ndarray:
        return np.zeros(self.frame_size, dtype=np.float32)

    def read(self) -> Optional[np.ndarray]:  # pragma: no cover - overridden
        raise NotImplementedError

    def status(self) -> dict:
        return {"open": self._open, "enabled": self._enabled,
                "sample_rate": self.sample_rate, "frame_size": self.frame_size,
                "backend": type(self).__name__}


class ArraySource(MicrophoneSource):
    """Deterministic source backed by an in-memory waveform — the test/offline mic.
    Yields successive frames; returns None when exhausted (or loops if `loop`)."""

    def __init__(self, samples: Optional[np.ndarray] = None, *, loop: bool = False) -> None:
        super().__init__()
        self._samples = (np.asarray(samples, dtype=np.float32)
                         if samples is not None else np.zeros(0, dtype=np.float32))
        self._pos = 0
        self._loop = loop

    def feed(self, samples: np.ndarray) -> None:
        self._samples = np.concatenate([self._samples, np.asarray(samples, dtype=np.float32)])

    def read(self) -> Optional[np.ndarray]:
        if self._pos + self.frame_size > len(self._samples):
            if self._loop and len(self._samples) >= self.frame_size:
                self._pos = 0
            else:
                return None
        frame = self._samples[self._pos:self._pos + self.frame_size]
        self._pos += self.frame_size          # advance even when disabled, so a
        if not self._enabled:                 # finite source still exhausts (privacy)
            return self._silence()
        return frame.astype(np.float32, copy=False)

    @property
    def remaining_frames(self) -> int:
        return max(0, (len(self._samples) - self._pos) // self.frame_size)


class LiveMicrophone(MicrophoneSource):
    """sounddevice-backed live mic (used at runtime; not required for tests)."""

    def __init__(self) -> None:
        super().__init__()
        self._stream = None

    def open(self) -> None:  # pragma: no cover - hardware
        if importlib.util.find_spec("sounddevice") is None:
            raise RuntimeError("sounddevice not installed")
        import sounddevice as sd
        self._stream = sd.InputStream(samplerate=self.sample_rate, channels=1,
                                      blocksize=self.frame_size, dtype="float32")
        self._stream.start()
        self._open = True

    def read(self) -> Optional[np.ndarray]:  # pragma: no cover - hardware
        if not self._enabled or self._stream is None:
            return self._silence()
        data, _ = self._stream.read(self.frame_size)
        return data.reshape(-1).astype(np.float32, copy=False)

    def close(self) -> None:  # pragma: no cover - hardware
        if self._stream is not None:
            self._stream.stop(); self._stream.close()
            self._stream = None
        self._open = False


# ── synthetic waveform helpers (tests / diagnostics) ──────────────────────────────
def tone(seconds: float, freq: float = 220.0, amplitude: float = 0.3,
         sr: int = SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(seconds * sr)) / sr
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(seconds: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    return np.zeros(int(seconds * sr), dtype=np.float32)


def noise(seconds: float, amplitude: float = 0.02, sr: int = SAMPLE_RATE,
          seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amplitude * rng.standard_normal(int(seconds * sr))).astype(np.float32)
