"""
core/services/world_model_service.py — FRIDAY V3 (M16)
WorldModelService — the only sanctioned door to the persistent model of reality. It
adapts the M5 `WorldModel` (entities + relationships) behind a stable API and degrades
to an in-memory fallback when no world model is injected, so spatial cognition can run
(and be tested) standalone without writing a database.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger("friday.services.world_model")


class WorldModelService:
    name = "world_model"

    def __init__(self, world_model=None) -> None:
        self._wm = world_model
        self._fallback: dict[str, dict] = {}      # used only when no world model is wired

    def observe(self, kind: str, name: str, *, state: Optional[dict] = None,
                attributes: Optional[dict] = None, confidence: float = 1.0) -> Optional[str]:
        if self._wm is not None:
            try:
                entity = self._wm.observe(kind, name, state=state or {},
                                          attributes=attributes or {}, confidence=confidence)
                return getattr(entity, "entity_id", None)
            except Exception:  # noqa: BLE001
                log.debug("world model observe failed", exc_info=True)
                return None
        eid = f"{kind}:{name}"
        rec = self._fallback.setdefault(eid, {"entity_id": eid, "kind": kind, "name": name,
                                              "state": {}, "attributes": {}})
        rec["state"].update(state or {})
        rec["attributes"].update(attributes or {})
        rec["confidence"] = confidence
        rec["updated_at"] = time.time()
        return eid

    def relate(self, source: str, target: str, relation: str, *,
               weight: float = 1.0, metadata: Optional[dict] = None) -> None:
        if self._wm is not None:
            try:
                from core.world.entities import WorldRelationship
                self._wm.add_relationship(WorldRelationship(
                    source_id=source, target_id=target, kind=relation,
                    weight=weight, metadata=metadata or {}))
            except Exception:  # noqa: BLE001
                log.debug("world model relate failed", exc_info=True)

    def get(self, entity_id: str) -> Optional[dict]:
        if self._wm is not None:
            try:
                e = self._wm.get_entity(entity_id)
                return e.to_dict() if e is not None else None
            except Exception:  # noqa: BLE001
                return None
        return self._fallback.get(entity_id)

    def health(self) -> dict:
        return {"status": "ok", "backend": "world_model" if self._wm else "in_memory_fallback",
                "fallback_entities": len(self._fallback)}
