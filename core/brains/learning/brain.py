"""
core/brains/learning/brain.py — FRIDAY V3 (M17 revision)
The Learning Brain (foundation). It watches the experience the LearningService collects
(tracking/relationship/observation samples) and surfaces candidate patterns with
reinforcement scores. Real training lands in a later milestone; the lifecycle, local
memory (pattern candidates, reinforcement scores, active-learning state), and reporting
are in place now so callers are unchanged later.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from ..base import CognitiveBrain, SituationReport


class LearningBrain(CognitiveBrain):
    name = "learning_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        for c in ("pattern_candidates", "reinforcement_scores"):
            self.local.cache(c, capacity=256)
        self.local.set("active_learning", False)
        self._learning = self._service("learning")
        self._counter: Counter = Counter()
        self._seen_ts = 0.0          # watermark: only NEW experience reinforces

    def observe(self):
        learning = self._resolve("_learning", "learning")
        return learning.samples(limit=50) if learning is not None else []

    def analyze(self, samples):
        # count only samples newer than the watermark — recounting the same
        # recent window every tick inflated reinforcement with tick rate, so
        # "patterns" emerged from idleness rather than experience
        for s in samples or []:
            ts = float(s.get("ts", 0.0) or 0.0)
            if ts <= self._seen_ts:
                continue
            key = f"{s.get('kind')}:{s.get('data', {}).get('category', '')}"
            self._counter[key] += 1
        if samples:
            self._seen_ts = max(self._seen_ts,
                                max(float(s.get("ts", 0.0) or 0.0) for s in samples))
        return {"top": self._counter.most_common(3), "total": sum(self._counter.values())}

    def update_local_memory(self, analysis) -> None:
        for pattern, score in analysis["top"]:
            self.local.push("pattern_candidates", pattern)
            self.local.push("reinforcement_scores", score)

    def reason(self, analysis):
        candidates = [{"pattern": p, "reinforcement": s} for p, s in analysis["top"] if s >= 3]
        self.local.set("active_learning", bool(candidates))
        return {"candidates": candidates, "total": analysis["total"]}

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if not insight["candidates"]:
            return None
        top = insight["candidates"][0]["pattern"]
        return self._report(f"Learning: {len(insight['candidates'])} candidate pattern(s); "
                            f"strongest is '{top}'.", confidence=0.5, priority=0.2,
                            category="learning", data={"candidates": insight["candidates"]})

    def health(self) -> dict:
        return {"status": "placeholder", "brain": self.name,
                "candidates": len(self.local.items("pattern_candidates"))}
