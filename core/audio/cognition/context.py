"""
core/audio/cognition/context.py — FRIDAY V3 (M15)
Audio Context Reasoning. A detected sound is not yet understanding — it must become a
*contextual observation* about reality. This module maps an `AuditoryEvent` to a
standardized `core.perception.Observation` (type = AUDIO) carrying a plain-language
interpretation, and routes it into the World Model through the SAME perception →
entity-resolver path every other sensor uses (never bypassing it).

The mapping is data (a `ContextRule` per sound), not code, so new sounds get reasoning
without editing logic; an unmapped sound falls back to a generic interpretation. The
reasoner performs the *interpretation*, not deliberation — planning/decision-making
stays in the Executive Brain.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.perception.models import (ObservationConfidence, ObservationSource,
                                    ObservationType, new_observation)

from .events import AuditoryEvent, SoundCategory

log = logging.getLogger("friday.audio.context")


@dataclass(frozen=True)
class ContextRule:
    """How one sound is interpreted: a reasoning sentence + the world entity it implies."""
    reasoning: str
    entity_kind: str
    entity_name: str
    impact: float = 0.5             # how much this sound should move attention/significance


# Default interpretations (override/extend via AudioContextReasoner(rules=...)).
_DEFAULT_RULES: dict[str, ContextRule] = {
    "doorbell": ContextRule("Someone may be at the door.", "event", "doorbell", 0.8),
    "door_knock": ContextRule("Someone is knocking at the door.", "event", "door_knock", 0.8),
    "phone_ringing": ContextRule("The phone is ringing.", "device", "phone", 0.7),
    "alarm": ContextRule("An alarm is going off — something needs attention.", "event", "alarm", 0.95),
    "timer": ContextRule("A timer has expired.", "event", "timer", 0.7),
    "keyboard_typing": ContextRule("The user is likely working at the computer.",
                                   "activity", "working", 0.4),
    "mouse_clicking": ContextRule("The user is active at the computer.", "activity", "working", 0.35),
    "running_water": ContextRule("Water is running — the user may be in the kitchen or bathroom.",
                                 "activity", "running_water", 0.5),
    "glass_breaking": ContextRule("Glass broke — a possible accident.", "event", "glass_breaking", 0.95),
    "crying": ContextRule("Someone may be crying — possible distress.", "state", "distress", 0.9),
    "laughter": ContextRule("Someone is laughing nearby.", "state", "laughter", 0.45),
    "dog_barking": ContextRule("A dog is barking.", "animal", "dog", 0.4),
    "cat_meowing": ContextRule("A cat is meowing.", "animal", "cat", 0.35),
}


class AudioContextReasoner:
    def __init__(self, *, perception=None, world_feed=None, rules: Optional[dict] = None) -> None:
        self._perception = perception        # core.perception.PerceptionManager (preferred)
        self._world_feed = world_feed        # fallback: a WorldFeed-like .observe(obs)
        self._rules = dict(_DEFAULT_RULES)
        if rules:
            self._rules.update(rules)
        self._count = 0

    def set_rule(self, sound: str, rule: ContextRule) -> None:
        self._rules[sound] = rule

    # ── reasoning ────────────────────────────────────────────────────────────────
    def reason(self, event: AuditoryEvent):
        """Turn a detection into a contextual AUDIO Observation (no World-Model bypass)."""
        rule = self._rules.get(event.sound)
        if rule is None:                      # graceful generic interpretation
            label = event.sound.replace("_", " ")
            rule = ContextRule(f"Heard {label}.", "event", event.sound,
                               0.7 if event.category == SoundCategory.EMERGENCY.value else 0.4)
        confidence = ObservationConfidence.clamp(event.confidence)
        obs = new_observation(
            ObservationType.AUDIO,
            ObservationSource("audio", kind="microphone"),
            payload={
                "name": rule.entity_name,
                "sound": event.sound,
                "category": event.category,
                "reasoning": rule.reasoning,
                "confidence": confidence,
                "entity_candidates": [{"kind": rule.entity_kind, "name": rule.entity_name,
                                       "confidence": confidence}],
                "evidence": {"event_id": event.event_id, "features": event.features,
                             "source": event.source},
            },
            confidence=confidence,
            metadata={
                "subject": f"audio:{event.sound}",
                "entity_kind": rule.entity_kind,
                "entity_name": rule.entity_name,
                "impact": rule.impact,
                "session_id": event.session_id,
                "sound_category": event.category,
            },
            timestamp=event.timestamp)
        self._route(obs)
        self._count += 1
        return obs

    def _route(self, obs) -> None:
        """Send the observation into cognition via the sanctioned perception path."""
        try:
            if self._perception is not None:
                self._perception.ingest(obs)
            elif self._world_feed is not None:
                self._world_feed.observe(obs)
        except Exception:  # noqa: BLE001 — a cognition failure must not break audio
            log.debug("audio context routing failed", exc_info=True)

    def metrics(self) -> dict:
        return {"observations": self._count, "rules": len(self._rules)}
