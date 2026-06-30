"""
core/perception/hub/events.py — FRIDAY V3 (M17)
The Perception Hub event vocabulary, published on the Runtime event bus (via the
RuntimeService) so the Executive, Memory, and future subsystems react without tight
coupling. str-valued so they are first-class bus keys.

Documented events:
  • observation.created    — a new unified observation was accepted + forwarded.
  • observation.updated     — an existing situation/observation was refreshed.
  • observation.merged      — multiple modality observations were fused into one.
  • observation.rejected    — an observation fell below confidence and could not be enriched.
  • context.changed         — the active context (room/task/activity/objects) changed.
  • timeline.updated        — the chronological timeline gained an observation.
  • perception.ready        — a perceive cycle completed and understanding is available.
  • reasoning.completed     — first-level reasoning produced conclusion(s).
  • situation.changed       — the overall situation summary changed (e.g. user started working).
"""

from __future__ import annotations

from enum import Enum


class HubEvent(str, Enum):
    OBSERVATION_CREATED = "perception.observation.created"
    OBSERVATION_UPDATED = "perception.observation.updated"
    OBSERVATION_MERGED = "perception.observation.merged"
    OBSERVATION_REJECTED = "perception.observation.rejected"
    CONTEXT_CHANGED = "perception.context.changed"
    TIMELINE_UPDATED = "perception.timeline.updated"
    PERCEPTION_READY = "perception.ready"
    REASONING_COMPLETED = "perception.reasoning.completed"
    SITUATION_CHANGED = "perception.situation.changed"
