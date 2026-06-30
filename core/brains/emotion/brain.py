"""
core/brains/emotion/brain.py — FRIDAY V3 (M17 revision)
The Emotion Brain (foundation). It maintains FRIDAY's affective context — mood history,
emotional context, social context — nudged by salient happenings (an emergency sound, a
person arriving). A full affect model lands later; the lifecycle, local memory, and
reporting exist now. Mood is a simple valence/arousal pair, decaying toward neutral.
"""

from __future__ import annotations

from typing import Optional

from ..base import CognitiveBrain, SituationReport

_NEUTRAL = {"valence": 0.0, "arousal": 0.0}


class EmotionBrain(CognitiveBrain):
    name = "emotion_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        for c in ("mood_history", "social_context"):
            self.local.cache(c, capacity=128)
        self.local.set("mood", dict(_NEUTRAL))
        self._emotion = self._service("emotion")

    def nudge(self, *, valence: float = 0.0, arousal: float = 0.0, reason: str = "") -> dict:
        """External affect nudge (e.g. from the Coordinator on a salient situation)."""
        mood = self.local.get("mood", dict(_NEUTRAL))
        mood = {"valence": _clamp(mood["valence"] * 0.7 + valence),
                "arousal": _clamp(mood["arousal"] * 0.7 + arousal)}
        self.local.set("mood", mood)
        self.local.push("mood_history", {"mood": mood, "reason": reason})
        return mood

    def reason(self, analysis):
        # decay toward neutral each tick
        mood = self.local.get("mood", dict(_NEUTRAL))
        mood = {"valence": _clamp(mood["valence"] * 0.9), "arousal": _clamp(mood["arousal"] * 0.9)}
        self.local.set("mood", mood)
        return mood

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        v, a = insight["valence"], insight["arousal"]
        if abs(v) < 0.2 and abs(a) < 0.2:
            return None                                  # neutral → nothing to report
        label = ("alert" if a > 0.4 else "positive" if v > 0.2 else
                 "negative" if v < -0.2 else "calm")
        return self._report(f"Affective context: {label} (valence {v:.2f}, arousal {a:.2f}).",
                            confidence=0.5, priority=0.3, category="emotion",
                            data={"mood": insight, "label": label})

    def health(self) -> dict:
        return {"status": "placeholder", "brain": self.name, "mood": self.local.get("mood")}


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))
