"""
core/brains/memory/knowledge_graph.py — FRIDAY V3 (M17 revision)
The semantic Knowledge Graph the Memory Brain owns — the foundation for future reasoning.
It connects the entities of FRIDAY's world (people, objects, rooms, concepts, projects,
habits, preferences, devices) with typed, weighted relationships and lets the system
traverse and explain them.

Distinct from the M7 knowledge store (which indexes distilled notes); this is a live
entity-relationship graph. Pure stdlib, in-memory, thread-safe.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


class NodeKind:
    PERSON = "person"
    OBJECT = "object"
    ROOM = "room"
    CONCEPT = "concept"
    PROJECT = "project"
    HABIT = "habit"
    PREFERENCE = "preference"
    DEVICE = "device"
    RELATIONSHIP = "relationship"
    ALL = ("person", "object", "room", "concept", "project", "habit", "preference",
           "device", "relationship")


def _slug(kind: str, label: str) -> str:
    return f"{kind}:" + (re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_") or "node")


@dataclass
class KGNode:
    node_id: str
    kind: str
    label: str
    attributes: dict = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"id": self.node_id, "kind": self.kind, "label": self.label,
                "attributes": self.attributes}


@dataclass
class KGEdge:
    source: str
    target: str
    relation: str
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)

    def key(self) -> tuple:
        return (self.source, self.target, self.relation)

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "relation": self.relation,
                "weight": round(self.weight, 3), "metadata": self.metadata}


class KnowledgeGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, KGNode] = {}
        self._edges: dict[tuple, KGEdge] = {}
        self._adj: dict[str, set] = {}
        self._lock = threading.RLock()

    # ── nodes ────────────────────────────────────────────────────────────────────
    def upsert_node(self, kind: str, label: str, *, attributes: Optional[dict] = None) -> KGNode:
        nid = _slug(kind, label)
        with self._lock:
            node = self._nodes.get(nid)
            if node is None:
                node = KGNode(node_id=nid, kind=kind, label=label,
                              attributes=dict(attributes or {}))
                self._nodes[nid] = node
                self._adj.setdefault(nid, set())
            else:
                if attributes:
                    node.attributes.update(attributes)
                node.updated = time.time()
            return node

    def get(self, node_id: str) -> Optional[KGNode]:
        return self._nodes.get(node_id)

    def find(self, term: str, *, kind: Optional[str] = None) -> list:
        t = (term or "").lower()
        with self._lock:
            return [n.to_dict() for n in self._nodes.values()
                    if (kind is None or n.kind == kind) and t in n.label.lower()]

    def by_kind(self, kind: str) -> list:
        with self._lock:
            return [n.to_dict() for n in self._nodes.values() if n.kind == kind]

    # ── edges ────────────────────────────────────────────────────────────────────
    def relate(self, source_id: str, target_id: str, relation: str, *,
               weight: float = 1.0, metadata: Optional[dict] = None) -> Optional[KGEdge]:
        with self._lock:
            if source_id not in self._nodes or target_id not in self._nodes:
                return None
            edge = KGEdge(source_id, target_id, relation, weight, dict(metadata or {}))
            existing = self._edges.get(edge.key())
            if existing is not None:
                existing.weight = max(existing.weight, weight)
                existing.metadata.update(metadata or {})
                return existing
            self._edges[edge.key()] = edge
            self._adj.setdefault(source_id, set()).add(target_id)
            self._adj.setdefault(target_id, set()).add(source_id)
            return edge

    def connect(self, src_kind: str, src_label: str, relation: str,
                tgt_kind: str, tgt_label: str, *, weight: float = 1.0) -> Optional[KGEdge]:
        """Convenience: upsert both nodes then relate them."""
        a = self.upsert_node(src_kind, src_label)
        b = self.upsert_node(tgt_kind, tgt_label)
        return self.relate(a.node_id, b.node_id, relation, weight=weight)

    # ── traversal ────────────────────────────────────────────────────────────────
    def neighbors(self, node_id: str) -> list:
        with self._lock:
            out = []
            for (s, t, rel), e in self._edges.items():
                if s == node_id:
                    out.append({"node": t, "relation": rel, "weight": e.weight})
                elif t == node_id:
                    out.append({"node": s, "relation": rel, "weight": e.weight})
            return out

    def related(self, kind: str, label: str) -> list:
        return self.neighbors(_slug(kind, label))

    def path(self, source_id: str, target_id: str, *, max_depth: int = 6) -> list:
        """Shortest relationship path (BFS) — returns the node-id chain or []."""
        with self._lock:
            if source_id not in self._nodes or target_id not in self._nodes:
                return []
            queue = deque([[source_id]])
            seen = {source_id}
            while queue:
                path = queue.popleft()
                if len(path) > max_depth:
                    continue
                last = path[-1]
                if last == target_id:
                    return path
                for nbr in self._adj.get(last, ()):
                    if nbr not in seen:
                        seen.add(nbr)
                        queue.append(path + [nbr])
            return []

    # ── observability ────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        with self._lock:
            return {"nodes": [n.to_dict() for n in self._nodes.values()],
                    "edges": [e.to_dict() for e in self._edges.values()]}

    def counts(self) -> dict:
        with self._lock:
            by_kind: dict[str, int] = {}
            for n in self._nodes.values():
                by_kind[n.kind] = by_kind.get(n.kind, 0) + 1
            return {"nodes": len(self._nodes), "edges": len(self._edges), "by_kind": by_kind}

    def health(self) -> dict:
        return {"status": "ok", **self.counts()}
