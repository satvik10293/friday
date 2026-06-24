"""
core/memory/service.py — FRIDAY 4.0
The Memory Service. The public face of FRIDAY's memory.

Ties together: WorkingMemory (RAM) + MemoryStore (SQLite source of truth) +
VectorIndex (derived, rebuildable) + Embedder. Implements the charter API:

  remember()      persist + embed + index, return id
  recall()        semantic recall (+ keyword fallback), with provenance scores
  consolidate()   summarize old episodic memory → semantic, demote raw → archival
  forget()        soft-delete (auditable) or hard purge
  amend()         supersede a memory with a correction (keeps lineage)
  rebuild_index() reconstruct the vector index from the store (recovery)

Invariants:
  • SQLite is truth; the vector index is always rebuildable from it.
  • Vectors are keyed by memory id (in-row embed_id) — no fragile side-list.
  • forget()/amend() never destroy lineage by default (soft-delete + supersede).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Callable, Optional

from .embedder import Embedder, get_embedder
from .index import VectorIndex, build_index
from .store import MemoryStore
from .working import WorkingMemory

log = logging.getLogger("friday.memory.service")


class MemoryService:
    def __init__(self, store: Optional[MemoryStore] = None,
                 index: Optional[VectorIndex] = None,
                 embedder: Optional[Embedder] = None,
                 working_capacity: int = 20) -> None:
        self._store = store or MemoryStore()
        self._embedder = embedder or get_embedder()
        self._index = index or build_index(self._embedder.dim)
        self._working = WorkingMemory(working_capacity)
        self._lock = threading.Lock()
        self._build_index_from_store()

    # ── core API ───────────────────────────────────────────────────────────────
    def remember(self, role: str, content: str, *, topic: str = "",
                 importance: float = 0.5, kind: str = "conversation",
                 tier: str = "episodic", session_id: str = "",
                 metadata: Optional[dict] = None) -> int:
        with self._lock:
            mem_id = self._store.insert(
                role, content, topic=topic, kind=kind, importance=importance,
                tier=tier, session_id=session_id, metadata=metadata,
            )
            vec = self._embedder.encode(content)
            self._index.add(mem_id, vec)               # keyed by mem_id == embed_id
            self._store.mark_embedded(mem_id, mem_id)
        self._working.add({"id": mem_id, "role": role, "content": content,
                           "topic": topic, "ts": time.time()})
        return mem_id

    def recall(self, query: str, k: int = 8) -> list[dict]:
        """Return up to k live memories most relevant to `query`, each annotated
        with a `score` (None for keyword hits). Suitable for Decision Log
        `memory_used` provenance."""
        with self._lock:
            if self._index.size() == 0:
                rows = self._store.keyword_search(query, limit=k)
                for r in rows:
                    r["score"] = None
                return rows

            qv = self._embedder.encode(query)
            hits = self._index.search(qv, k * 3)       # over-fetch; deleted rows get filtered
            score_by = {i: s for i, s in hits}
            rows = self._store.by_ids(list(score_by.keys()))  # excludes soft-deleted
            for r in rows:
                r["score"] = score_by.get(r["id"])
            rows.sort(key=lambda r: (r["score"] is not None, r["score"] or 0.0), reverse=True)
            top = rows[:k]

        for r in top:
            self._store.touch(r["id"])
        return top

    def consolidate(self, summarizer: Optional[Callable[[str, list[dict]], str]] = None,
                    older_than_s: float = 86_400, min_cluster: int = 2) -> dict:
        """Cluster old episodic memories by topic, summarize each cluster into a
        semantic memory, and demote the raw episodes to archival. Runs off the
        request path (schedule it on the runtime)."""
        summarizer = summarizer or self._default_summarizer
        cutoff = time.time() - older_than_s
        candidates = self._store.episodic_older_than(cutoff)
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in candidates:
            groups[r["topic"] or "general"].append(r)

        created = 0
        archived = 0
        for topic, items in groups.items():
            if len(items) < min_cluster:
                continue
            summary = summarizer(topic, items)
            self.remember(
                "system", summary, topic=topic, kind="summary", tier="semantic",
                importance=0.7, metadata={"source_ids": [i["id"] for i in items]},
            )
            for i in items:
                self._store.update_tier(i["id"], "archival")
                archived += 1
            created += 1
        log.info("consolidate: %d summaries, %d archived", created, archived)
        return {"summaries_created": created, "archived": archived}

    def forget(self, mem_id: int, hard: bool = False) -> bool:
        with self._lock:
            if self._store.get(mem_id) is None:
                return False
            if hard:
                try:
                    self._index.remove(mem_id)
                except NotImplementedError:
                    pass  # ANN can't delete; rebuild_index() compacts later
                self._store.hard_delete(mem_id)
            else:
                self._store.soft_delete(mem_id)  # stays out of recall via by_ids filter
        return True

    def amend(self, mem_id: int, new_content: str, *, importance: Optional[float] = None,
              metadata: Optional[dict] = None) -> Optional[int]:
        old = self._store.get(mem_id)
        if old is None:
            return None
        new_id = self.remember(
            old["role"], new_content, topic=old["topic"], kind=old["kind"],
            importance=importance if importance is not None else old["importance"],
            tier=old["tier"], session_id=old.get("session_id", ""),
            metadata={**(metadata or {}), "amends": mem_id},
        )
        self._store.set_superseded(mem_id, new_id)
        return new_id

    def rebuild_index(self) -> int:
        """Reconstruct the vector index from the store — recovery path after
        corruption, backend swap, or hard purges."""
        with self._lock:
            self._index.reset()
            ids: list[int] = []
            vecs = []
            for mem_id, content in self._store.iter_live():
                ids.append(mem_id)
                vecs.append(self._embedder.encode(content))
                self._store.mark_embedded(mem_id, mem_id)
            if ids:
                import numpy as np
                self._index.add_many(ids, np.asarray(vecs, dtype="float32"))
        log.info("rebuilt index: %d vectors", len(ids))
        return len(ids)

    # ── context assembly (token/char-budgeted) ────────────────────────────────
    def assemble_context(self, query: str, max_chars: int = 1500, k: int = 8) -> str:
        parts: list[str] = []
        budget = max_chars
        for r in self.recall(query, k=k):
            line = f"[{r['kind']}/{r['role']}] {r['content'][:240]}".replace("\n", " ")
            if len(line) > budget:
                break
            parts.append(line)
            budget -= len(line)
        return "Relevant memory:\n" + "\n".join(parts) if parts else ""

    # ── diagnostics / runtime integration ─────────────────────────────────────
    def working(self) -> WorkingMemory:
        return self._working

    def stats(self) -> dict:
        c = self._store.counts()
        return {
            **c,
            "index_size": self._index.size(),
            "index_backend": getattr(self._index, "backend", "?"),
            "embedder": getattr(self._embedder, "backend", "?"),
            "working": len(self._working),
        }

    def health(self) -> dict:
        s = self.stats()
        # drift check: index should track live, embeddable rows
        s["index_consistent"] = s["index_size"] >= (s["total"] - s["deleted"]) - 1
        return s

    def attach(self, runtime, consolidate_every_s: float = 3_600) -> None:
        """Register with the runtime: health surface + scheduled consolidation."""
        runtime.register_health("memory", self.health)
        runtime.schedule("memory.consolidate", self.consolidate, every=consolidate_every_s)

    # ── internals ──────────────────────────────────────────────────────────────
    def _build_index_from_store(self) -> None:
        if self._index.size() > 0:
            return
        ids, vecs = [], []
        for mem_id, content in self._store.iter_live():
            ids.append(mem_id)
            vecs.append(self._embedder.encode(content))
        if ids:
            import numpy as np
            self._index.add_many(ids, np.asarray(vecs, dtype="float32"))
            log.info("loaded %d vectors from store", len(ids))

    @staticmethod
    def _default_summarizer(topic: str, items: list[dict]) -> str:
        head = "; ".join(i["content"][:80].replace("\n", " ") for i in items[:6])
        return f"Summary of {len(items)} memories on '{topic}': {head}"[:600]


# ── singleton ───────────────────────────────────────────────────────────────────
_service: Optional[MemoryService] = None
_svc_lock = threading.Lock()


def get_memory_service() -> MemoryService:
    global _service
    with _svc_lock:
        if _service is None:
            _service = MemoryService()
    return _service
