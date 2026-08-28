"""
core/cognition_core/entity_registry.py — FRIDAY 6.0 (M13)
The Persistent Entity Registry. Owns the lifecycle of entities with opaque, permanent
stable ids (ENT_000001). Identity never changes; human-readable labels are metadata
that accumulate. Merging two ids (when the resolver discovers they were the same
thing) folds one into the other and re-points aliases — the surviving id is permanent.

Persistence is delegated to an injected `EntityRepository`; this module holds no I/O.
"""

from __future__ import annotations

from typing import Optional

from .interfaces import EntityRepository
from .matching import normalize
from .models import Entity


class PersistentEntityRegistry:
    def __init__(self, repository: EntityRepository) -> None:
        self._repo = repository

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def create(self, kind: str, label: str, *, attributes: Optional[dict] = None,
               confidence: float = 1.0) -> Entity:
        entity = Entity(stable_id=self._repo.allocate_id(), kind=kind, primary_label=label,
                        labels=[label] if label else [],
                        attributes=dict(attributes or {}),
                        confidence=max(0.0, min(1.0, confidence)))
        self._repo.add(entity)
        if label:
            self._repo.add_alias(normalize(label), entity.stable_id, kind)
        return entity

    def get(self, stable_id: str) -> Optional[Entity]:
        return self._repo.get(stable_id)

    def all(self) -> list[Entity]:
        return self._repo.all()

    def by_kind(self, kind: str) -> list[Entity]:
        return self._repo.by_kind(kind)

    def find_by_label(self, kind: str, label: str) -> Optional[Entity]:
        return self._repo.find_by_label(kind, label)

    def resolve_alias(self, normalized: str, kind: Optional[str] = None) -> Optional[str]:
        return self._repo.resolve_alias(normalized, kind)

    # ── enrichment ──────────────────────────────────────────────────────────────
    def add_alias(self, stable_id: str, name: str) -> None:
        entity = self._repo.get(stable_id)
        if entity is None:
            return
        entity.add_label(name)
        entity.touch()
        self._repo.update(entity)
        self._repo.add_alias(normalize(name), stable_id, entity.kind)

    def reinforce(self, stable_id: str, *, attributes: Optional[dict] = None,
                  confidence: Optional[float] = None) -> Optional[Entity]:
        """Update an entity after a fresh observation resolves to it."""
        entity = self._repo.get(stable_id)
        if entity is None:
            return None
        if attributes:
            entity.attributes.update(attributes)
        if confidence is not None:
            entity.confidence = max(entity.confidence, min(1.0, confidence))
        entity.touch()
        self._repo.update(entity)
        return entity

    # ── merge (two ids were the same thing) ─────────────────────────────────────
    def merge(self, keep_id: str, drop_id: str) -> Optional[Entity]:
        """Fold `drop_id` into `keep_id`. The kept id is permanent; the dropped id's
        labels/aliases/attributes move over and it is recorded in `merged_from`."""
        if keep_id == drop_id:
            return self._repo.get(keep_id)
        keep = self._repo.get(keep_id)
        drop = self._repo.get(drop_id)
        if keep is None or drop is None:
            return keep
        for label in drop.labels:
            keep.add_label(label)
        for alias in self._repo.aliases_for(drop_id):
            self._repo.add_alias(alias, keep_id, keep.kind)
        # keep's own attributes win; fill gaps from drop
        merged_attrs = {**drop.attributes, **keep.attributes}
        keep.attributes = merged_attrs
        keep.confidence = max(keep.confidence, drop.confidence)
        keep.merged_from = list(dict.fromkeys(keep.merged_from + [drop_id] + drop.merged_from))
        keep.touch()
        self._repo.update(keep)
        self._repo.remove(drop_id)
        return keep

    def counts(self) -> dict:
        return self._repo.counts()
