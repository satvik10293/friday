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

    def __init__(self, model_size: str = "base", *, language: Optional[str] = "en") -> None:
        self._model_size = model_size
        # pin the language (default English): auto-detect on a short, noisy
        # ~1s fragment mis-guesses (it once picked Spanish at p=0.32 on a
        # clear English utterance), which garbles the transcript AND wastes a
        # detection pass every segment. None restores auto-detect.
        self._language = language
        self._model = None

    def _get(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio: np.ndarray) -> Transcript:
        segments, info = self._get().transcribe(
            np.asarray(audio, dtype=np.float32), language=self._language,
            vad_filter=True)                     # drop non-speech padding
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        # confidence from the acoustic model, NOT language detection: whisper's
        # per-segment avg_logprob (~ -1.0 poor … 0 perfect) mapped to 0..1,
        # penalised by no_speech_prob. The old code reported
        # language_probability, so a clear utterance scored low whenever
        # language detection was merely unsure — dragging it below the
        # clarify/route thresholds and making her fall silent.
        conf = _acoustic_confidence(segs) if text else 0.0
        return Transcript(text, conf, self.name)


def _acoustic_confidence(segments: list) -> float:
    """Map whisper's per-segment avg_logprob to 0..1, penalised by the
    probability the audio was non-speech. Duration-weighted so a long clear
    clause isn't outvoted by a short noisy one."""
    import math
    total_w = score = 0.0
    for s in segments:
        dur = max(0.1, float(getattr(s, "end", 0.0)) - float(getattr(s, "start", 0.0)))
        logprob = float(getattr(s, "avg_logprob", -1.0))
        no_speech = float(getattr(s, "no_speech_prob", 0.0))
        p = math.exp(max(-5.0, min(0.0, logprob)))       # e^logprob ∈ (0,1]
        score += dur * p * (1.0 - min(1.0, no_speech))
        total_w += dur
    return round(score / total_w, 3) if total_w else 0.0


def _stt_config() -> dict:
    """Read the non-secret stt block from friday_config.json (best-effort)."""
    import json
    from pathlib import Path
    try:
        root = Path(__file__).resolve().parents[3]
        cfg = json.loads((root / "friday_config.json").read_text(encoding="utf-8"))
        return cfg.get("stt") or {}
    except (OSError, ValueError):
        return {}


def get_transcriber() -> Transcriber:
    """Best available local transcriber, else the deterministic fake. Honours
    the `stt` config block (model size + pinned language)."""
    if importlib.util.find_spec("faster_whisper") is not None:
        try:
            cfg = _stt_config()
            lang = cfg.get("language", "en")
            return WhisperTranscriber(cfg.get("model", "base"),
                                      language=(lang or None))
        except Exception:  # noqa: BLE001
            pass
    return FakeTranscriber()
