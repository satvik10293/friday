"""
core/brains/memory/brain.py — FRIDAY V3 (M17 revision)
The Memory Brain — the single owner of FRIDAY's memory. It replaces direct memory access
throughout the project: every remember/recall/forget/promote/consolidate request goes
through here. It manages the tiered hierarchy (Working → Core), the semantic Knowledge
Graph, and (for durability) a wrapped long-term backend (the M2 MemoryService) — which it
reaches only through the service interface, never importing its internals.

As a Cognitive Brain it also runs a maintenance lifecycle (promotion, forgetting,
periodic consolidation) and reports its state. Never-raises; thread-safe.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..base import CognitiveBrain, SituationReport
from .knowledge_graph import KnowledgeGraph, NodeKind
from .tiers import MemoryTier, TieredMemory

log = logging.getLogger("friday.brains.memory")

_CONSOLIDATE_EVERY = 20         # ticks between consolidation passes


class MemoryBrain(CognitiveBrain):
    name = "memory_brain"

    def __init__(self, *, services=None, config: Optional[dict] = None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self.tiers = TieredMemory(
            working_capacity=int(self.config.get("working_capacity", 64)),
            stale_after_s=float(self.config.get("stale_after_s", 600.0)))
        self.graph = KnowledgeGraph()
        self._durable = self._service("memory")          # M2-backed durable long-term store
        self._durable_tier = MemoryTier.LONG_TERM
        self._last_promotions = 0

    # ── public memory API (the sanctioned way to use memory) ─────────────────────
    def remember(self, content: str, *, importance: float = 0.4, confidence: float = 0.5,
                 kind: str = "event", user_confirmed: bool = False,
                 metadata: Optional[dict] = None) -> dict:
        item = self.tiers.store(content, importance=importance, confidence=confidence,
                                kind=kind, user_confirmed=user_confirmed, metadata=metadata)
        if item.tier >= self._durable_tier:
            self._persist(content, kind, metadata)
        return item.to_dict()

    def recall(self, query: str, *, limit: int = 8) -> list:
        hits = self.tiers.recall(query, limit=limit)
        durable = self._resolve("_durable", "memory")
        if durable is not None and len(hits) < limit:
            try:
                for d in durable.recall(query, limit=limit - len(hits)):
                    hits.append({"content": d.get("content", ""), "tier": "long_term",
                                 "source": "durable"})
            except Exception:  # noqa: BLE001
                log.debug("durable recall failed", exc_info=True)
        return hits

    def reinforce(self, mem_id: str, *, confirm: bool = False) -> Optional[dict]:
        item = self.tiers.reinforce(mem_id, confirm=confirm)
        return item.to_dict() if item is not None else None

    def promote(self) -> list:
        promotions = self.tiers.promote()
        for p in promotions:                             # newly long-term/core → persist
            if p["to"] in ("long_term", "core"):
                self._persist(p["content"], "promoted", {"tier": p["to"]})
        return promotions

    def consolidate(self) -> list:
        return self.tiers.consolidate()

    def forget(self, mem_id: str) -> bool:
        return self.tiers.forget(mem_id)

    # ── knowledge graph API ──────────────────────────────────────────────────────
    def learn_fact(self, subject_kind: str, subject: str, relation: str,
                   object_kind: str, obj: str, *, weight: float = 1.0) -> Optional[dict]:
        edge = self.graph.connect(subject_kind, subject, relation, object_kind, obj, weight=weight)
        return edge.to_dict() if edge is not None else None

    def note_entity(self, kind: str, label: str, *, attributes: Optional[dict] = None) -> dict:
        return self.graph.upsert_node(kind, label, attributes=attributes).to_dict()

    def related(self, kind: str, label: str) -> list:
        return self.graph.related(kind, label)

    def knowledge_graph(self) -> KnowledgeGraph:
        return self.graph

    # ── ingest a situation (called by the Coordinator/Executive) ─────────────────
    def remember_situation(self, situation: dict) -> dict:
        """Store a unified situation + thread its entities into the knowledge graph."""
        summary = situation.get("summary") or situation.get("situation") or "situation"
        importance = _num(situation.get("priority", situation.get("importance", 0.5)), 0.5)
        confidence = _num(situation.get("confidence", 0.6), 0.6)
        record = self.remember(summary, importance=importance, confidence=confidence,
                               kind="situation", metadata={"id": situation.get("id")})
        room = situation.get("location") or situation.get("room")
        if room:
            self.graph.upsert_node(NodeKind.ROOM, room)
        objects = situation.get("related_objects") or situation.get("objects") or []
        people = situation.get("related_people") or situation.get("people") or []
        for obj in objects:
            if room:                     # no room → note the entity, skip junk edges
                self.graph.connect(NodeKind.OBJECT, obj, "in_room", NodeKind.ROOM, room)
            else:
                self.graph.upsert_node(NodeKind.OBJECT, obj)
        for person in people:
            if room:
                self.graph.connect(NodeKind.PERSON, person, "in_room", NodeKind.ROOM, room)
            else:
                self.graph.upsert_node(NodeKind.PERSON, person)
        return record

    # ── Cognitive Brain lifecycle (maintenance) ──────────────────────────────────
    def reason(self, analysis):
        promotions = self.promote()
        forgotten = self.tiers.forget_stale()
        consolidations = []
        if self._ticks % _CONSOLIDATE_EVERY == 0:
            consolidations = self.consolidate()
        self._last_promotions = len(promotions)
        return {"promotions": promotions, "forgotten": forgotten,
                "consolidations": consolidations}

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        counts = self.tiers.counts()
        if not insight or (not insight["promotions"] and not insight["consolidations"]
                           and self._ticks > 1):
            return None
        return self._report(
            f"Memory: {counts['total']} items "
            f"({counts['core']} core, {counts['semantic']} semantic, {counts['working']} working); "
            f"+{len(insight['promotions'])} promoted",
            confidence=0.9, priority=0.3, category="memory",
            data={"counts": counts, "promotions": insight["promotions"],
                  "graph": self.graph.counts()})

    # ── durable backend ──────────────────────────────────────────────────────────
    def _persist(self, content: str, kind: str, metadata: Optional[dict]) -> None:
        durable = self._resolve("_durable", "memory")    # late-registered service
        if durable is None:
            return
        try:
            durable.remember(content, kind=kind, metadata=metadata or {})
        except Exception:  # noqa: BLE001
            log.debug("durable persist failed", exc_info=True)

    # ── observability ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {**super().metrics(), "tiers": self.tiers.metrics(), "graph": self.graph.counts()}

    def health(self) -> dict:
        return {"status": "ok" if self._last_tick_ok else "degraded",
                "brain": self.name, "tiers": self.tiers.counts(),
                "graph": self.graph.counts()}


def _num(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
