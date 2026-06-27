"""
core/cognition_core/entity_resolver.py — FRIDAY 6.0 (M13)
The Entity Resolver. Every observation about a thing is resolved to a permanent
stable id through a fixed pipeline:

    observation → exact match → alias resolution → normalization →
    similarity matching → persistent lookup → create (if necessary) → stable id

Identity persists independently of names: when a new surface name resolves to an
existing entity, the name is registered as an alias so it resolves directly next
time. Resolution decisions are observable (metrics + optional events).
"""

from __future__ import annotations

from typing import Callable, Optional

from .entity_registry import PersistentEntityRegistry
from .matching import normalize, similarity
from .models import Entity, ResolveMethod, ResolveResult


class EntityResolver:
    def __init__(self, registry: PersistentEntityRegistry, *,
                 similarity_threshold: float = 0.82,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 metrics=None) -> None:
        self._registry = registry
        self._threshold = similarity_threshold
        self._on_event = on_event
        self._metrics = metrics

    def resolve(self, kind: str, name: str, *, attributes: Optional[dict] = None,
                confidence: float = 1.0) -> ResolveResult:
        name = (name or "").strip()
        norm = normalize(name)

        # 1) exact match (identical primary label)
        exact = self._registry.find_by_label(kind, name)
        if exact is not None:
            return self._hit(exact, ResolveMethod.EXACT, 1.0, name, attributes, confidence)

        # 2) alias resolution (a normalized name we've already linked)
        if norm:
            sid = self._registry.resolve_alias(norm, kind)
            if sid is not None:
                entity = self._registry.get(sid)
                if entity is not None:
                    return self._hit(entity, ResolveMethod.ALIAS, 1.0, name, attributes, confidence)

        # 3) normalization match (same canonical key as an existing label)
        candidates = self._registry.by_kind(kind)
        for e in candidates:
            if normalize(e.primary_label) == norm and norm:
                return self._hit(e, ResolveMethod.NORMALIZED, 1.0, name, attributes, confidence)

        # 4) similarity match (fuzzy — typos / minor variants)
        best, best_score = None, 0.0
        for e in candidates:
            score = max([similarity(name, e.primary_label)] +
                        [similarity(name, lbl) for lbl in e.labels])
            if score > best_score:
                best, best_score = e, score
        if best is not None and best_score >= self._threshold:
            return self._hit(best, ResolveMethod.SIMILARITY, best_score, name, attributes, confidence)

        # 5/6) create a new persistent entity
        entity = self._registry.create(kind, name, attributes=attributes, confidence=confidence)
        self._count("created")
        self._emit("entity.created", {"stable_id": entity.stable_id, "kind": kind, "label": name})
        return ResolveResult(stable_id=entity.stable_id, created=True,
                             method=ResolveMethod.CREATED.value, score=1.0, entity=entity)

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _hit(self, entity: Entity, method: ResolveMethod, score: float, name: str,
             attributes: Optional[dict], confidence: float) -> ResolveResult:
        # learn the new surface name as an alias so it resolves directly next time
        if name and normalize(name) not in {normalize(l) for l in entity.labels}:
            self._registry.add_alias(entity.stable_id, name)
            if method == ResolveMethod.SIMILARITY:
                self._count("collision")     # a fuzzy variant collapsed onto one entity
        self._registry.reinforce(entity.stable_id, attributes=attributes, confidence=confidence)
        self._count("resolved")
        self._count(f"method.{method.value}")
        self._emit("entity.resolved",
                   {"stable_id": entity.stable_id, "method": method.value, "score": round(score, 3)})
        return ResolveResult(stable_id=entity.stable_id, created=False,
                             method=method.value, score=round(score, 4),
                             entity=self._registry.get(entity.stable_id))

    def _count(self, key: str) -> None:
        if self._metrics is not None:
            self._metrics.incr(key)

    def _emit(self, kind: str, data: dict) -> None:
        if self._on_event is not None:
            self._on_event(kind, data)
