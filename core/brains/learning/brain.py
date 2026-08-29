"""
core/brains/learning/brain.py — FRIDAY V3 (M17 revision → flywheel completed)
The Learning Brain. It watches the experience the LearningService collects
(tracking/relationship/observation samples), surfaces candidate patterns with
reinforcement scores, and — once a pattern is seen enough — PROMOTES it into a
durable, persisted lesson through the LearningService. That closes the loop it
used to leave open: it now not only notices patterns, it keeps them so the rest
of the system can recall and act on them. A pattern is promoted only when it has
genuinely more evidence than last time, so idle ticks never inflate learning.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from ..base import CognitiveBrain, SituationReport

_PROMOTE_AT = 3          # a pattern becomes a lesson after this much evidence


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
        self._promoted: dict = {}    # pattern -> evidence at last promotion (no tick inflation)

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
        candidates = [{"pattern": p, "reinforcement": s}
                      for p, s in analysis["top"] if s >= _PROMOTE_AT]
        self.local.set("active_learning", bool(candidates))
        learned_now = self._promote(candidates)
        return {"candidates": candidates, "total": analysis["total"],
                "learned_now": learned_now}

    def _promote(self, candidates) -> list:
        """Turn qualifying candidates into durable lessons via the learning
        service — but only when a pattern has MORE evidence than the last time it
        was promoted, so a persistent candidate is not re-learned every idle tick.
        Degrades silently if the service can't learn; never breaks a tick."""
        learning = self._resolve("_learning", "learning")
        learn = getattr(learning, "learn", None) if learning is not None else None
        if not callable(learn):
            return []
        learned_now: list = []
        for c in candidates:
            pattern, evidence = c["pattern"], c["reinforcement"]
            if evidence <= self._promoted.get(pattern, 0):
                continue                                 # no new evidence — skip
            kind, _, category = pattern.partition(":")
            try:
                lesson = learn(pattern, kind=kind, category=category,
                               meta={"evidence": evidence})
            except Exception:  # noqa: BLE001 — learning must never break a tick
                continue
            self._promoted[pattern] = evidence
            if lesson.get("new"):
                learned_now.append(pattern)
        return learned_now

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        learned = insight.get("learned_now") or []
        if learned:
            return self._report(
                f"Learned {len(learned)} new lesson(s); first: '{learned[0]}'.",
                confidence=0.6, priority=0.3, category="learning",
                data={"learned": learned, "candidates": insight["candidates"]})
        if not insight["candidates"]:
            return None
        top = insight["candidates"][0]["pattern"]
        return self._report(f"Learning: {len(insight['candidates'])} candidate pattern(s); "
                            f"strongest is '{top}'.", confidence=0.5, priority=0.2,
                            category="learning", data={"candidates": insight["candidates"]})

    def health(self) -> dict:
        learning = self._resolve("_learning", "learning")
        lessons = 0
        get_lessons = getattr(learning, "lessons", None) if learning is not None else None
        if callable(get_lessons):
            try:
                lessons = len(get_lessons())
            except Exception:  # noqa: BLE001
                lessons = 0
        return {"status": "ok", "brain": self.name,
                "candidates": len(self.local.items("pattern_candidates")),
                "lessons": lessons}
