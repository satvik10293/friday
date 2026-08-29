"""
core/brains/emotion/brain.py — FRIDAY V3 (M17 revision → affect model completed)

The Emotion Brain maintains FRIDAY's affective context as a core-affect pair
(valence = pleasant/unpleasant, arousal = calm/activated) that decays toward
neutral, and now:

  · names the feeling — a principled valence/arousal → discrete-emotion map
    (neutral, calm, content, energized, alert, concerned, alarmed), and
  · appraises events by MEANING — appraise("emergency"/"success"/...) turns an
    event category into the right affective shift, so the mood reflects what is
    actually happening, not just raw external nudges.

Still bounded and honest: 2-D core affect with discrete labels + event
appraisal, thread-safe, never raises. It informs (situation reports carry the
named emotion); it does not by itself drive actions.
"""

from __future__ import annotations

import threading
from typing import Optional

from ..base import CognitiveBrain, SituationReport

_NEUTRAL = {"valence": 0.0, "arousal": 0.0}

# event category → (Δvalence, Δarousal) at full intensity; scaled by priority
_APPRAISAL = {
    "emergency": (-0.5, 0.7), "safety": (-0.4, 0.6), "alert": (-0.3, 0.5),
    "error": (-0.3, 0.3), "failure": (-0.4, 0.3), "problem": (-0.25, 0.3),
    "success": (0.5, 0.3), "goal_complete": (0.5, 0.3), "praise": (0.5, 0.2),
    "positive": (0.4, 0.2), "social": (0.2, 0.1), "person": (0.2, 0.1),
    "learning": (0.15, 0.1),
}


def _emotion_label(v: float, a: float) -> str:
    """Name the feeling from the core-affect pair."""
    if abs(v) < 0.15 and abs(a) < 0.15:
        return "neutral"
    if a >= 0.4:                          # activated
        return "energized" if v >= 0.15 else "alarmed" if v <= -0.15 else "alert"
    if v >= 0.15:                         # pleasant, not highly activated
        return "content"
    if v <= -0.15:                        # unpleasant, not highly activated
        return "concerned"
    return "calm"                         # some arousal, flat valence


class EmotionBrain(CognitiveBrain):
    name = "emotion_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        for c in ("mood_history", "social_context"):
            self.local.cache(c, capacity=128)
        self.local.set("mood", dict(_NEUTRAL))
        self._emotion = self._service("emotion")
        # nudge()/appraise() (coordinator thread) and reason() (tick thread) both
        # read-modify-write the mood; without this lock a decay could erase a
        # concurrent nudge
        self._mood_lock = threading.Lock()

    def nudge(self, *, valence: float = 0.0, arousal: float = 0.0, reason: str = "") -> dict:
        """Raw affect nudge (e.g. from the Coordinator on a salient situation)."""
        with self._mood_lock:
            mood = self.local.get("mood", dict(_NEUTRAL))
            mood = {"valence": _clamp(mood["valence"] * 0.7 + valence),
                    "arousal": _clamp(mood["arousal"] * 0.7 + arousal)}
            self.local.set("mood", mood)
        self.local.push("mood_history", {"mood": mood, "reason": reason})
        return mood

    def appraise(self, category: str, *, priority: float = 0.5) -> dict:
        """Semantic nudge: map an event category to the right affective shift,
        scaled by how salient it was. Unknown categories are affectively neutral."""
        dv, da = _APPRAISAL.get((category or "").lower(), (0.0, 0.0))
        scale = max(0.0, min(1.0, float(priority)))
        return self.nudge(valence=dv * scale, arousal=da * scale,
                          reason=f"appraise:{category}")

    def reason(self, analysis):
        # decay toward neutral each tick
        with self._mood_lock:
            mood = self.local.get("mood", dict(_NEUTRAL))
            mood = {"valence": _clamp(mood["valence"] * 0.9),
                    "arousal": _clamp(mood["arousal"] * 0.9)}
            self.local.set("mood", mood)
        return mood

    def emotion(self) -> str:
        """The current named feeling."""
        mood = self.local.get("mood", dict(_NEUTRAL))
        return _emotion_label(mood["valence"], mood["arousal"])

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        v, a = insight["valence"], insight["arousal"]
        if abs(v) < 0.2 and abs(a) < 0.2:
            return None                                  # neutral → nothing to report
        label = _emotion_label(v, a)
        return self._report(f"Affective context: {label} (valence {v:.2f}, arousal {a:.2f}).",
                            confidence=0.5, priority=0.3, category="emotion",
                            data={"mood": insight, "label": label})

    def health(self) -> dict:
        mood = self.local.get("mood", dict(_NEUTRAL))
        return {"status": "ok", "brain": self.name, "mood": mood,
                "emotion": _emotion_label(mood["valence"], mood["arousal"])}


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))
