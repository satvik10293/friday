"""
core/perception/world_feed.py — FRIDAY 4.0 (M6)
WorldFeed: the adapter that lets the M5 WorldModel "observe()" Observation objects
directly, without modifying world_model.py (additive integration). It translates an
Observation into the WorldModel's existing `observe(kind, name, state, ...)` call.

Promotion is governed by rules (high confidence, high significance, repeated
occurrence, goal relevance) evaluated in the PerceptionManager; WorldFeed performs
the actual write once a promotion is decided.
"""

from __future__ import annotations

import logging
from typing import Optional

from .models import Observation

log = logging.getLogger("friday.perception.world_feed")


class WorldFeed:
    def __init__(self, world_model) -> None:
        self._world = world_model
        self._promoted = 0

    def observe(self, obs: Observation) -> Optional[object]:
        """Write an Observation into the world model as an entity, merging state.
        Returns the resulting WorldEntity (or None if no world model)."""
        if self._world is None:
            return None
        kind, name = self._entity_for(obs)
        state = dict(obs.payload)
        state["_observed_at"] = obs.timestamp
        entity = self._world.observe(kind, name, state=state,
                                     attributes={"observation_type": obs.type.value},
                                     confidence=obs.confidence)
        self._promoted += 1
        return entity

    def feed(self, observations: list) -> int:
        n = 0
        for obs in observations:
            if self.observe(obs) is not None:
                n += 1
        return n

    @property
    def promoted(self) -> int:
        return self._promoted

    @staticmethod
    def _entity_for(obs: Observation) -> tuple[str, str]:
        """Map an observation to a (kind, name) world entity. Fusion/app observations
        carry an explicit entity name; otherwise the subject identifies it."""
        kind = obs.metadata.get("entity_kind") or obs.type.value
        name = obs.metadata.get("entity_name") or obs.payload.get("name") \
            or obs.source.name
        return kind, str(name)
