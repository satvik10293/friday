"""
core/knowledge/knowledge_graph.py — FRIDAY 4.0 (M7)
The knowledge relationship engine. Models knowledge as a graph so FRIDAY can walk
from a concept to its dependencies and explain connections:

    Python → Flask → Authentication → Sessions

Relations: `parent` / `child` (hierarchy, stored as inverse pairs) and `related`
(symmetric). Operates over the KnowledgeStore's knowledge_links table.
"""

from __future__ import annotations

from collections import deque
from typing import Optional

from .knowledge_models import KnowledgeLink, KnowledgeRelation


class KnowledgeGraph:
    def __init__(self, store) -> None:
        self._store = store

    # ── mutation ───────────────────────────────────────────────────────────────
    def add_relation(self, source_id: str, target_id: str,
                     relation: str = KnowledgeRelation.RELATED.value) -> None:
        """Add a relation. `related` is symmetric; `parent`/`child` are stored as an
        inverse pair so the hierarchy is navigable in both directions."""
        self._store.add_link(KnowledgeLink(source_id, target_id, relation))
        if relation == KnowledgeRelation.RELATED.value:
            self._store.add_link(KnowledgeLink(target_id, source_id, relation))
        elif relation == KnowledgeRelation.PARENT.value:
            self._store.add_link(KnowledgeLink(target_id, source_id,
                                               KnowledgeRelation.CHILD.value))
        elif relation == KnowledgeRelation.CHILD.value:
            self._store.add_link(KnowledgeLink(target_id, source_id,
                                               KnowledgeRelation.PARENT.value))

    def remove_relation(self, source_id: str, target_id: str,
                        relation: str = KnowledgeRelation.RELATED.value) -> None:
        self._store.remove_link(source_id, target_id, relation)
        inverse = {KnowledgeRelation.RELATED.value: KnowledgeRelation.RELATED.value,
                   KnowledgeRelation.PARENT.value: KnowledgeRelation.CHILD.value,
                   KnowledgeRelation.CHILD.value: KnowledgeRelation.PARENT.value}.get(relation)
        if inverse:
            self._store.remove_link(target_id, source_id, inverse)

    # ── queries ────────────────────────────────────────────────────────────────
    def neighbors(self, knowledge_id: str, relation: Optional[str] = None) -> list[str]:
        """Ids directly linked from `knowledge_id` (optionally filtered by relation)."""
        out = []
        for link in self._store.links_for(knowledge_id):
            if link.source_id != knowledge_id:
                continue
            if relation is None or link.relation == relation:
                out.append(link.target_id)
        return out

    def traverse(self, start_id: str, relation: Optional[str] = None,
                 max_depth: int = 5) -> list[str]:
        """Breadth-first traversal from `start_id`, returning visited ids in order
        (excluding the start). Bounded by `max_depth` so cycles can't loop forever."""
        seen = {start_id}
        order: list[str] = []
        q: deque = deque([(start_id, 0)])
        while q:
            node, depth = q.popleft()
            if depth >= max_depth:
                continue
            for nxt in self.neighbors(node, relation):
                if nxt not in seen:
                    seen.add(nxt)
                    order.append(nxt)
                    q.append((nxt, depth + 1))
        return order

    def path(self, start_id: str, target_id: str, max_depth: int = 8) -> list[str]:
        """Shortest relation path from start to target (inclusive), or [] if none."""
        if start_id == target_id:
            return [start_id]
        seen = {start_id}
        q: deque = deque([[start_id]])
        while q:
            trail = q.popleft()
            if len(trail) > max_depth:
                continue
            for nxt in self.neighbors(trail[-1]):
                if nxt == target_id:
                    return trail + [nxt]
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(trail + [nxt])
        return []

    def explain(self, start_id: str, target_id: str) -> str:
        """Human-readable chain of titles connecting two knowledge entries."""
        trail = self.path(start_id, target_id)
        if not trail:
            return ""
        titles = []
        for kid in trail:
            e = self._store.get(kid)
            titles.append(e.title if e else kid)
        return " → ".join(titles)
