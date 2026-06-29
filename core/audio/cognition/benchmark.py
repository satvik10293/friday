"""
core/audio/cognition/benchmark.py — FRIDAY V3 (M15)
Benchmarks for Auditory Cognition on deterministic synthetic audio (no microphone, no
models). Measures detection throughput and latency, plus separability of the model-free
detectors on clearly-distinct synthetic signals, and de-duplication correctness.

Reported:
  • feature_extraction_ms   — mean feature-extraction time per window
  • detect_per_s            — windows classified per second (end-to-end engine.analyze)
  • frame_fps              — frames/second through process_frame
  • category_accuracy      — fraction of clearly-separable signals classed into the right category
  • dedup_precision        — duplicates correctly rejected
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .config import EventDetectionConfig
from .dedup import SpeechDeduplicator
from .engine import AudioEventEngine
from .features import SAMPLE_RATE, extract_features

SR = SAMPLE_RATE


def _tone(f: float, sec: float, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(sec * SR)) / SR
    return (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)


def _noise(sec: float, amp: float = 0.3, seed: int = 0) -> np.ndarray:
    return (amp * np.random.default_rng(seed).standard_normal(int(sec * SR))).astype(np.float32)


def _impulses(sec: float, n: int, amp: float = 0.6, seed: int = 0) -> np.ndarray:
    x = np.zeros(int(sec * SR), dtype=np.float32)
    rng = np.random.default_rng(seed)
    for pos in rng.integers(0, x.size - 64, size=n):
        x[pos:pos + 64] += amp * rng.standard_normal(64).astype(np.float32)
    return x


@dataclass
class AudioBenchmarkReport:
    windows: int
    feature_extraction_ms: float
    detect_per_s: float
    frame_fps: float
    category_accuracy: float
    dedup_precision: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


# clearly-separable signals → expected *category* (heuristic detectors are category-robust)
def _labeled_signals():
    return [
        ("tone", _tone(700, 0.6), "alert"),            # tonal chime → doorbell/alert
        ("broadband", _noise(0.6, seed=3), "emergency"),  # bright shatter-like → glass
        ("impulses", _impulses(0.6, 12), "activity"),  # many clicks → keyboard
    ]


def run_benchmark(repeats: int = 40) -> AudioBenchmarkReport:
    eng = AudioEventEngine(EventDetectionConfig(min_confidence=0.45, per_type_cooldown_s=0.0))

    # feature extraction latency
    win = _tone(440, 0.6)
    t0 = time.perf_counter()
    for _ in range(repeats):
        extract_features(win)
    feat_ms = (time.perf_counter() - t0) / repeats * 1000.0

    # detection throughput
    t1 = time.perf_counter()
    for _ in range(repeats):
        eng.analyze(win)
    detect_per_s = repeats / (time.perf_counter() - t1)

    # frame throughput (20 ms frames)
    frame = np.zeros(320, dtype=np.float32)
    t2 = time.perf_counter()
    nframes = repeats * 10
    for _ in range(nframes):
        eng.process_frame(frame)
    frame_fps = nframes / (time.perf_counter() - t2)

    # category separability
    correct = 0
    labeled = _labeled_signals()
    for _name, sig, expected in labeled:
        ev = eng.analyze(sig, ts=time.time() + np.random.rand())
        if ev is not None and ev.category == expected:
            correct += 1
    category_accuracy = correct / len(labeled)

    # dedup precision
    dd = SpeechDeduplicator()
    dd.check("turn on the lights")
    rejected = sum(1 for _ in range(5) if not dd.check("turn on the lights").accepted)
    dedup_precision = rejected / 5.0

    return AudioBenchmarkReport(
        windows=repeats, feature_extraction_ms=round(feat_ms, 4),
        detect_per_s=round(detect_per_s, 1), frame_fps=round(frame_fps, 1),
        category_accuracy=round(category_accuracy, 3), dedup_precision=round(dedup_precision, 3))


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(run_benchmark().to_dict(), indent=2))
