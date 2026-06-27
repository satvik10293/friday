"""
core/audio/listener/metrics.py — FRIDAY 4.0 (M12.1)
Listening metrics: wake activations (and false / missed), recognition failures,
average latency, average confidence, and total speech duration. Bounded windows →
stable over a long runtime. Raw audio is never recorded here (privacy).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class ListeningMetrics:
    window: int = 500
    wake_activations: int = 0
    false_activations: int = 0
    missed_activations: int = 0
    recognition_failures: int = 0
    commands: int = 0
    speech_seconds: float = 0.0
    _latencies: deque = field(default_factory=lambda: deque(maxlen=500))
    _confidences: deque = field(default_factory=lambda: deque(maxlen=500))

    def record_wake(self, *, false_positive: bool = False) -> None:
        self.wake_activations += 1
        if false_positive:
            self.false_activations += 1

    def record_missed_wake(self) -> None:
        self.missed_activations += 1

    def record_command(self, *, latency_ms: float, confidence: float,
                       speech_s: float, recognized: bool) -> None:
        self.commands += 1
        self._latencies.append(float(latency_ms))
        self._confidences.append(float(confidence))
        self.speech_seconds = round(self.speech_seconds + speech_s, 3)
        if not recognized:
            self.recognition_failures += 1

    @staticmethod
    def _avg(seq) -> float:
        return round(sum(seq) / len(seq), 3) if seq else 0.0

    def snapshot(self) -> dict:
        return {
            "wake_activations": self.wake_activations,
            "false_activations": self.false_activations,
            "missed_activations": self.missed_activations,
            "recognition_failures": self.recognition_failures,
            "commands": self.commands,
            "speech_seconds": self.speech_seconds,
            "avg_latency_ms": self._avg(self._latencies),
            "avg_confidence": self._avg(self._confidences),
        }
