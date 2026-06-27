"""
core/audio/listener/transcription.py — FRIDAY 4.0 (M12.1)
Speech-to-text behind a small protocol so the engine is swappable. `FakeTranscriber`
is the deterministic offline/test engine (it returns scripted text per segment);
`WhisperTranscriber` wraps faster-whisper when installed. All transcription is local.
"""

from __future__ import annotations

import importlib.util
from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .microphone import SAMPLE_RATE


@dataclass
class Transcript:
    text: str
    confidence: float = 0.0
    engine: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class Transcriber:
    name = "base"
    def transcribe(self, audio: np.ndarray) -> Transcript:  # pragma: no cover
        raise NotImplementedError


class FakeTranscriber(Transcriber):
    """Deterministic engine: returns scripted phrases in order, or a fixed default.
    The offline + test transcriber — no audio model required."""

    name = "fake"

    def __init__(self, script: Optional[list[str]] = None, *,
                 default: str = "", confidence: float = 0.9) -> None:
        self._script: deque = deque(script or [])
        self._default = default
        self._confidence = confidence

    def push(self, text: str) -> None:
        self._script.append(text)

    def transcribe(self, audio: np.ndarray) -> Transcript:
        if self._script:
            return Transcript(self._script.popleft(), self._confidence, self.name)
        if len(audio) == 0:
            return Transcript("", 0.0, self.name)
        return Transcript(self._default, self._confidence if self._default else 0.0, self.name)


class WhisperTranscriber(Transcriber):  # pragma: no cover - optional heavy dep
    """faster-whisper engine (local). Loaded lazily; used at runtime when present."""

    name = "faster-whisper"

    def __init__(self, model_size: str = "base") -> None:
        self._model_size = model_size
        self._model = None

    def _get(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio: np.ndarray) -> Transcript:
        segments, info = self._get().transcribe(
            np.asarray(audio, dtype=np.float32), language=None)
        text = " ".join(s.text.strip() for s in segments).strip()
        conf = float(getattr(info, "language_probability", 0.0)) or (0.7 if text else 0.0)
        return Transcript(text, conf, self.name)


def get_transcriber() -> Transcriber:
    """Best available local transcriber, else the deterministic fake."""
    if importlib.util.find_spec("faster_whisper") is not None:
        try:
            return WhisperTranscriber()
        except Exception:  # noqa: BLE001
            pass
    return FakeTranscriber()
