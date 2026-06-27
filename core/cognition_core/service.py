"""
core/cognition_core/service.py — FRIDAY 6.0 (M13)
The Cognition Core facade — the single seam the rest of FRIDAY uses for persistent
entity identity, beliefs, and the self model. Composes the resolver, registry, belief
system, and self model over injected repositories (SQLite by default; in-memory for
tests). Publishes metrics + events; exposes a machine-readable manifest and a Mission
Control dashboard payload.

Cognition never touches SQLite directly here — only the injected repositories do.
Side-effect-free to import (the store opens when CognitionCore is constructed).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from .belief_system import BeliefSystem
from .entity_registry import PersistentEntityRegistry
from .entity_resolver import EntityResolver
from .interfaces import BeliefRepository, EntityRepository
from .metrics import CognitionMetrics
from .models import Belief, Entity, Evidence, ResolveResult, SelfModelSnapshot
from .repositories import SqliteBeliefRepository, SqliteEntityRepository
from .self_model import SelfModel
from .world_integration import EntityLinker, ResolvingWorldFeed

log = logging.getLogger("friday.cognition")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class CognitionCore:
    def __init__(self, *, entity_repository: Optional[EntityRepository] = None,
                 belief_repository: Optional[BeliefRepository] = None,
                 runtime=None, similarity_threshold: float = 0.82,
                 goal_service=None, sensor_registry=None, society=None,
                 resource_monitor=None, cognitive_state=None, intelligence=None) -> None:
        self._entity_repo = entity_repository if entity_repository is not None \
            else SqliteEntityRepository()
        self._belief_repo = belief_repository if belief_repository is not None \
            else SqliteBeliefRepository()
        self._runtime = runtime
        self.metrics = CognitionMetrics()

        self.registry = PersistentEntityRegistry(self._entity_repo)
        self.resolver = EntityResolver(self.registry, similarity_threshold=similarity_threshold,
                                       on_event=self._emit, metrics=self.metrics)
        self.beliefs = BeliefSystem(self._belief_repo, on_event=self._emit, metrics=self.metrics)
        self.self_model = SelfModel(
            goal_service=goal_service, sensor_registry=sensor_registry, society=society,
            resource_monitor=resource_monitor, cognitive_state=cognitive_state,
            intelligence=intelligence)
        self._lock = threading.RLock()

    # ── entity resolution ───────────────────────────────────────────────────────
    def resolve(self, kind: str, name: str, *, attributes: Optional[dict] = None,
                confidence: float = 1.0) -> ResolveResult:
        with self._lock:
            return self.resolver.resolve(kind, name, attributes=attributes, confidence=confidence)

    def get_entity(self, stable_id: str) -> Optional[Entity]:
        return self.registry.get(stable_id)

    def entities(self) -> list[Entity]:
        return self.registry.all()

    def entities_by_kind(self, kind: str) -> list[Entity]:
        return self.registry.by_kind(kind)

    def merge(self, keep_id: str, drop_id: str) -> Optional[Entity]:
        """Merge two stable ids that were the same thing. Beliefs about the dropped
        id are re-pointed to the kept id; the kept id is permanent."""
        with self._lock:
            entity = self.registry.merge(keep_id, drop_id)
            if entity is not None and keep_id != drop_id:
                self.beliefs.repoint_subject(drop_id, keep_id)
                self.metrics.incr("merged")
                self._emit("entity.merged", {"kept": keep_id, "dropped": drop_id})
            return entity

    def linker(self) -> EntityLinker:
        return EntityLinker(self.resolver)

    def resolving_world_feed(self, world_model) -> ResolvingWorldFeed:
        return ResolvingWorldFeed(world_model, self.resolver)

    # ── beliefs ─────────────────────────────────────────────────────────────────
    def assert_belief(self, subject: str, predicate: str, value: Any, *,
                      confidence: float = 0.6, source: str = "system",
                      evidence: Optional[Evidence] = None) -> Belief:
        with self._lock:
            return self.beliefs.assert_belief(subject, predicate, value,
                                              confidence=confidence, source=source,
                                              evidence=evidence)

    def beliefs_about(self, subject: str) -> list[Belief]:
        return self.beliefs.about(subject)

    def get_belief(self, belief_id: str) -> Optional[Belief]:
        return self.beliefs.get(belief_id)

    def query_beliefs(self, **kw) -> list[Belief]:
        return self.beliefs.query(**kw)

    def revise_belief(self, belief_id: str, **kw) -> Optional[Belief]:
        with self._lock:
            return self.beliefs.revise(belief_id, **kw)

    def retract_belief(self, belief_id: str) -> bool:
        with self._lock:
            return self.beliefs.retract(belief_id)

    def verify_belief(self, belief_id: str, **kw) -> Optional[Belief]:
        with self._lock:
            return self.beliefs.verify(belief_id, **kw)

    # ── self model ──────────────────────────────────────────────────────────────
    def self_snapshot(self) -> SelfModelSnapshot:
        return self.self_model.snapshot()

    # ── observability ───────────────────────────────────────────────────────────
    def metrics_snapshot(self) -> dict:
        return self.metrics.snapshot()

    def dashboard(self) -> dict:
        ec = self._entity_repo.counts()
        bc = self._belief_repo.counts()
        by_kind: dict[str, int] = {}
        for e in self.registry.all():
            by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
        return {"title": "Cognition", "entities": ec.get("entities", 0),
                "aliases": ec.get("aliases", 0), "beliefs": bc.get("beliefs", 0),
                "active_beliefs": bc.get("active", 0), "by_kind": by_kind,
                "metrics": self.metrics.snapshot(),
                "self_model": self.self_snapshot().to_dict()}

    def health(self) -> dict:
        return {"status": "ok", "entities": self._entity_repo.counts().get("entities", 0),
                "beliefs": self._belief_repo.counts().get("beliefs", 0)}

    def manifest(self) -> dict:
        """The subsystem's machine-readable architecture record (single source of
        truth: architecture.json)."""
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        self._runtime = runtime
        try:
            runtime.register_health("cognition", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)

    def _emit(self, kind: str, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(kind, data=data, source="cognition")
        except Exception:  # noqa: BLE001
            log.debug("event emit failed", exc_info=True)

    def close(self) -> None:
        self._entity_repo.close()
        self._belief_repo.close()


_core: Optional[CognitionCore] = None
_lock = threading.Lock()


def get_cognition_core(**kw) -> CognitionCore:
    global _core
    with _lock:
        if _core is None:
            _core = CognitionCore(**kw)
    return _core
