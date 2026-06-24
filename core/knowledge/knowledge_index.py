"""
core/knowledge/knowledge_index.py — FRIDAY 4.0 (M7)
The knowledge retrieval cache. A thin semantic-search layer over the M2 vector
stack (HashingEmbedder + NumpyFlatIndex / FAISS), specialised for knowledge.

This index is NOT a source of truth: it is fully rebuildable from the
KnowledgeStore (which is itself rebuildable from the Obsidian vault). It exists
only to keep retrieval fast as the knowledge base grows.

Knowledge entries are keyed by string ids, but vector backends key by int, so
this class owns a bidirectional str↔int map (the int is the entry's `embed_id`).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from core.memory.embedder import Embedder, HashingEmbedder
from core.memory.index import NumpyFlatIndex, VectorIndex, build_index

log = logging.getLogger("friday.knowledge.index")


class KnowledgeIndex:
    """Semantic index over knowledge text. Reuses M2's embedder + vector index
    by composition. Backends: FAISS (if installed) or exact numpy fallback."""

    def __init__(self, embedder: Optional[Embedder] = None,
                 index: Optional[VectorIndex] = None) -> None:
        self._embedder = embedder if embedder is not None else HashingEmbedder()
        self._index = index if index is not None else build_index(self._embedder.dim)
        self._next_int = 1
        self._str_to_int: dict[str, int] = {}
        self._int_to_str: dict[int, str] = {}

    @property
    def backend(self) -> str:
        return getattr(self._index, "backend", "unknown")

    def _alloc(self, knowledge_id: str) -> int:
        iid = self._str_to_int.get(knowledge_id)
        if iid is None:
            iid = self._next_int
            self._next_int += 1
            self._str_to_int[knowledge_id] = iid
            self._int_to_str[iid] = knowledge_id
        return iid

    # ── mutation ───────────────────────────────────────────────────────────────
    def add(self, knowledge_id: str, text: str) -> int:
        """Embed `text` and index it under `knowledge_id`. Returns the int embed id.
        Re-adding an existing id replaces its vector."""
        if knowledge_id in self._str_to_int:
            self.remove(knowledge_id)
        iid = self._alloc(knowledge_id)
        vec = self._embedder.encode(text)
        self._index.add(iid, vec)
        return iid

    def remove(self, knowledge_id: str) -> None:
        iid = self._str_to_int.pop(knowledge_id, None)
        if iid is None:
            return
        self._int_to_str.pop(iid, None)
        try:
            self._index.remove(iid)
        except NotImplementedError:
            # ANN backends (HNSW) can't delete in place; the stale vector is
            # filtered out at search time and cleared on the next rebuild.
            log.debug("index backend cannot remove; will drop on rebuild")

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return up to `k` (knowledge_id, score) pairs ranked by similarity."""
        if self._index.size() == 0:
            return []
        vec = self._embedder.encode(query)
        out: list[tuple[str, float]] = []
        # over-fetch so removed-but-not-purged ints can be skipped
        for iid, score in self._index.search(vec, max(k * 2, k)):
            sid = self._int_to_str.get(int(iid))
            if sid is not None:
                out.append((sid, float(score)))
            if len(out) >= k:
                break
        return out

    def rebuild(self, items: list[tuple[str, str]]) -> int:
        """Drop everything and re-index from `(knowledge_id, text)` pairs. The
        canonical recovery path: rebuild from the store/vault at any time."""
        self.reset()
        for kid, text in items:
            self.add(kid, text)
        return self.size()

    def reset(self) -> None:
        self._index.reset()
        self._str_to_int.clear()
        self._int_to_str.clear()
        self._next_int = 1

    def size(self) -> int:
        return len(self._str_to_int)

    def health(self) -> dict:
        return {"status": "ok", "backend": self.backend,
                "vectors": self.size(), "dim": self._embedder.dim}
