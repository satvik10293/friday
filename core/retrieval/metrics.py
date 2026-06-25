"""
core/retrieval/metrics.py — FRIDAY 4.0 (M10)
Retrieval quality metrics. Tracks search latency, result confidence, and embedding
quality online, and can score retrieval accuracy (precision@k) against a labeled
set when one is supplied. These feed the Mission Control Resource/Knowledge panels.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class RetrievalMetrics:
    window: int = 200
    _latencies: deque = field(default_factory=lambda: deque(maxlen=200))
    _confidences: deque = field(default_factory=lambda: deque(maxlen=200))
    _top_scores: deque = field(default_factory=lambda: deque(maxlen=200))
    searches: int = 0
    hits: int = 0
    accuracy_samples: list = field(default_factory=list)   # precision@k samples

    def record_search(self, *, latency_ms: float, confidence: float,
                      top_score: float, hit: bool) -> None:
        self.searches += 1
        self._latencies.append(float(latency_ms))
        self._confidences.append(float(confidence))
        self._top_scores.append(float(top_score))
        if hit:
            self.hits += 1

    def record_accuracy(self, precision_at_k: float) -> None:
        self.accuracy_samples.append(float(precision_at_k))

    @staticmethod
    def _avg(seq) -> float:
        return (sum(seq) / len(seq)) if seq else 0.0

    def snapshot(self) -> dict:
        return {
            "searches": self.searches,
            "hit_rate": round(self.hits / self.searches, 4) if self.searches else 0.0,
            "avg_latency_ms": round(self._avg(self._latencies), 3),
            "avg_confidence": round(self._avg(self._confidences), 4),
            "avg_embedding_quality": round(self._avg(self._top_scores), 4),
            "retrieval_accuracy": round(self._avg(self.accuracy_samples), 4)
            if self.accuracy_samples else None,
        }
