"""
core/knowledge/knowledge_search.py — FRIDAY 4.0 (M8)
Unified knowledge retrieval. One entry point that searches FRIDAY's whole mind in
priority order and stops as soon as it is confident enough:

    1. Working Memory   (right-now buffer, M2)
    2. Memory Service   (durable experiences, M2/M3)
    3. Knowledge Store  (distilled understanding, M7)
    4. Knowledge Graph  (related concepts, M7)
    5. External Sources (last resort, only if confidence < threshold)

Local-first is enforced: external retrieval happens only when the best local
confidence is below `threshold` AND the caller explicitly allows it. Additive —
composes the M2 MemoryService and the M7 KnowledgeService without modifying them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

log = logging.getLogger("friday.knowledge.search")


class SearchTier(str, Enum):
    WORKING = "working_memory"
    MEMORY = "memory_service"
    KNOWLEDGE = "knowledge_store"
    GRAPH = "knowledge_graph"
    EXTERNAL = "external"
    NONE = "none"


@dataclass
class SearchResult:
    query: str = ""
    tier: str = SearchTier.NONE.value
    confidence: float = 0.0
    items: list = field(default_factory=list)        # list[dict]
    related: list = field(default_factory=list)      # list[dict] (graph neighbours)
    candidate: Optional[object] = None               # unstored external KnowledgeEntry
    trace: list = field(default_factory=list)         # tiers consulted, in order

    @property
    def found(self) -> bool:
        return bool(self.items)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        if self.candidate is not None and hasattr(self.candidate, "to_dict"):
            d["candidate"] = self.candidate.to_dict()
        return d


class KnowledgeSearch:
    def __init__(self, knowledge_service, memory_service=None, *,
                 threshold: float = 0.5, k: int = 5) -> None:
        self._k = knowledge_service
        self._mem = memory_service
        self._threshold = threshold
        self._k_default = k

    # ── tiers ──────────────────────────────────────────────────────────────────
    def _search_working(self, query: str) -> list[dict]:
        if self._mem is None:
            return []
        terms = {w for w in query.lower().split() if len(w) > 2}
        hits = []
        for item in self._mem.working().snapshot():
            content = str(item.get("content", "")).lower()
            if terms and any(t in content for t in terms):
                hits.append({**item, "tier": SearchTier.WORKING.value})
        return hits

    def _search_memory(self, query: str, k: int) -> list[dict]:
        if self._mem is None:
            return []
        rows = self._mem.recall(query, k=k)
        for r in rows:
            r["tier"] = SearchTier.MEMORY.value
        return rows

    def _search_knowledge(self, query: str, k: int) -> list[dict]:
        entries = self._k.search_knowledge(query, k=k)
        return [{**e.to_dict(), "tier": SearchTier.KNOWLEDGE.value} for e in entries]

    def _graph_related(self, knowledge_id: str, limit: int = 5) -> list[dict]:
        out = []
        for nid in self._k.graph.neighbors(knowledge_id)[:limit]:
            e = self._k.store.get(nid)
            if e is not None:
                out.append({**e.to_dict(), "tier": SearchTier.GRAPH.value})
        return out

    # ── confidence ─────────────────────────────────────────────────────────────
    @staticmethod
    def _confidence(items: list[dict], tier: str) -> float:
        if not items:
            return 0.0
        if tier == SearchTier.KNOWLEDGE.value:
            return max(float(i.get("confidence", 0.0)) for i in items)
        if tier == SearchTier.MEMORY.value:
            scores = [i["score"] for i in items if i.get("score") is not None]
            return max(scores) if scores else 0.55
        if tier == SearchTier.WORKING.value:
            return 0.6
        return 0.4

    # ── public ─────────────────────────────────────────────────────────────────
    def search(self, query: str, *, k: Optional[int] = None,
               allow_external: bool = False) -> SearchResult:
        """Search the cascade in priority order. Returns the first tier that meets
        the confidence threshold; otherwise the best local tier, and (only if
        allowed) an external candidate."""
        k = k or self._k_default
        result = SearchResult(query=query)

        best_items: list[dict] = []
        best_conf = 0.0
        best_tier = SearchTier.NONE.value

        for tier, fetch in (
            (SearchTier.WORKING.value, lambda: self._search_working(query)),
            (SearchTier.MEMORY.value, lambda: self._search_memory(query, k)),
            (SearchTier.KNOWLEDGE.value, lambda: self._search_knowledge(query, k)),
        ):
            result.trace.append(tier)
            items = fetch()
            if not items:
                continue
            conf = self._confidence(items, tier)
            if conf > best_conf:
                best_items, best_conf, best_tier = items, conf, tier
            if conf >= self._threshold:
                result.items = items
                result.tier = tier
                result.confidence = conf
                if tier == SearchTier.KNOWLEDGE.value and items:
                    result.related = self._graph_related(items[0]["id"])
                    result.trace.append(SearchTier.GRAPH.value)
                return result

        # nothing cleared the bar — keep the best local tier we saw
        result.items = best_items
        result.tier = best_tier
        result.confidence = best_conf
        if best_tier == SearchTier.KNOWLEDGE.value and best_items:
            result.related = self._graph_related(best_items[0]["id"])
            result.trace.append(SearchTier.GRAPH.value)

        # external is the genuine last resort
        if best_conf < self._threshold and allow_external:
            result.trace.append(SearchTier.EXTERNAL.value)
            ext = self._k.answer(query, k=k, allow_external=True)
            if ext.get("source") == "external" and ext.get("candidate") is not None:
                result.tier = SearchTier.EXTERNAL.value
                result.candidate = ext["candidate"]
                result.confidence = ext["candidate"].confidence
        return result
