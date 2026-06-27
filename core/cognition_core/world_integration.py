"""
core/cognition_core/world_integration.py — FRIDAY 6.0 (M13)
Additive integration with the M5 World Model + M6 perception. `ResolvingWorldFeed`
subclasses the M6 `WorldFeed`: before writing an observation into the World Model, it
resolves the thing to a permanent stable id and stamps that id onto the entity. M6 is
untouched (composition/subclass), and observations therefore never bypass entity
resolution.
"""

from __future__ import annotations

from typing import Optional

from core.perception.world_feed import WorldFeed
from .entity_resolver import EntityResolver


class ResolvingWorldFeed(WorldFeed):
    """A WorldFeed that resolves a stable entity id before writing to the World Model."""

    def __init__(self, world_model, resolver: EntityResolver) -> None:
        super().__init__(world_model)
        self._resolver = resolver

    def observe(self, obs) -> Optional[object]:
        if self._world is None:
            return None
        kind, name = self._entity_for(obs)
        result = self._resolver.resolve(kind, name, attributes={
            "observation_type": obs.type.value}, confidence=obs.confidence)
        state = dict(obs.payload)
        state["_observed_at"] = obs.timestamp
        entity = self._world.observe(
            kind, name, state=state,
            attributes={"observation_type": obs.type.value, "stable_id": result.stable_id},
            confidence=obs.confidence)
        self._promoted += 1
        return entity


class EntityLinker:
    """Convenience for any subsystem to resolve a (kind, name) to a stable id without
    going through perception — the sanctioned way to reference real-world entities."""

    def __init__(self, resolver: EntityResolver) -> None:
        self._resolver = resolver

    def link(self, kind: str, name: str, *, attributes: Optional[dict] = None,
             confidence: float = 1.0) -> str:
        return self._resolver.resolve(kind, name, attributes=attributes,
                                      confidence=confidence).stable_id
