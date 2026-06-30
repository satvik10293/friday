"""
core/brains/memory/tiers.py — FRIDAY V3 (M17 revision)
The tiered memory the Memory Brain manages. A memory rises through the hierarchy as it
proves itself:

    Working → Short-Term → Episodic → Semantic → Long-Term → Core

Promotion depends on reinforcement, frequency, confidence, user confirmation, and
importance. Recall reinforces (use it or lose it); stale low-tier memories are forgotten;
episodic memories consolidate into semantic summaries. Pure, in-memory, thread-safe — the
Memory Brain wraps a durable backend (M2 MemoryService) for the highest tiers.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable, Optional


class MemoryTier(IntEnum):
    WORKING = 0
    SHORT_TERM = 1
    EPISODIC = 2
    SEMANTIC = 3
    LONG_TERM = 4
    CORE = 5

    @property
    def label(self) -> str:
        return self.name.lower()


# score bands → highest tier an item may occupy
_BANDS = [(0.90, MemoryTier.CORE), (0.75, MemoryTier.LONG_TERM), (0.60, MemoryTier.SEMANTIC),
          (0.40, MemoryTier.EPISODIC), (0.20, MemoryTier.SHORT_TERM), (0.0, MemoryTier.WORKING)]


def new_memory_id() -> str:
    return "MEM_" + uuid.uuid4().hex[:12]


@dataclass
class MemoryItem:
    content: str
    tier: MemoryTier = MemoryTier.WORKING
    importance: float = 0.4
    confidence: float = 0.5
    reinforcement: float = 0.0
    access_count: int = 0
    user_confirmed: bool = False
    created: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    kind: str = "event"
    metadata: dict = field(default_factory=dict)
    mem_id: str = field(default_factory=new_memory_id)

    def score(self) -> float:
        reinforce = min(1.0, self.reinforcement / 5.0)
        freq = min(1.0, self.access_count / 10.0)
        s = 0.25 * self.confidence + 0.25 * self.importance + 0.3 * reinforce + 0.2 * freq
        if self.user_confirmed:
            s += 0.5            # user-confirmed memories are core knowledge
        return max(0.0, min(1.0, s))

    def target_tier(self) -> MemoryTier:
        s = self.score()
        for threshold, tier in _BANDS:
            if s >= threshold:
                return tier
        return MemoryTier.WORKING

    def to_dict(self) -> dict:
        return {"mem_id": self.mem_id, "content": self.content, "tier": self.tier.label,
                "importance": round(self.importance, 3), "confidence": round(self.confidence, 3),
                "reinforcement": round(self.reinforcement, 3), "access_count": self.access_count,
                "user_confirmed": self.user_confirmed, "kind": self.kind,
                "score": round(self.score(), 3)}


class TieredMemory:
    def __init__(self, *, working_capacity: int = 64, stale_after_s: float = 600.0) -> None:
        self._items: dict[str, MemoryItem] = {}
        self._working_capacity = working_capacity
        self._stale_after = stale_after_s
        self._lock = threading.RLock()
        self._promotions = 0

    # ── store / reinforce ────────────────────────────────────────────────────────
    def store(self, content: str, *, importance: float = 0.4, confidence: float = 0.5,
              kind: str = "event", user_confirmed: bool = False,
              metadata: Optional[dict] = None) -> MemoryItem:
        item = MemoryItem(content=content, importance=importance, confidence=confidence,
                          kind=kind, user_confirmed=user_confirmed, metadata=dict(metadata or {}))
        item.tier = item.target_tier()
        with self._lock:
            self._items[item.mem_id] = item
            self._enforce_working_capacity()
        return item

    def reinforce(self, mem_id: str, *, amount: float = 1.0, confirm: bool = False) -> Optional[MemoryItem]:
        with self._lock:
            item = self._items.get(mem_id)
            if item is None:
                return None
            item.reinforcement += amount
            item.access_count += 1
            item.last_access = time.time()
            if confirm:
                item.user_confirmed = True
            return item

    # ── promotion ────────────────────────────────────────────────────────────────
    def promote(self) -> list:
        """Re-evaluate every item and raise it toward its earned tier (never demotes).
        Returns the promotions that occurred."""
        promotions = []
        with self._lock:
            for item in self._items.values():
                target = item.target_tier()
                if target > item.tier:
                    promotions.append({"mem_id": item.mem_id, "from": item.tier.label,
                                       "to": target.label, "content": item.content})
                    item.tier = target
                    self._promotions += 1
        return promotions

    # ── recall (reinforces) ──────────────────────────────────────────────────────
    def recall(self, query: str, *, limit: int = 8) -> list:
        q = (query or "").lower()
        with self._lock:
            hits = [i for i in self._items.values() if q in i.content.lower()]
            hits.sort(key=lambda i: (int(i.tier), i.last_access), reverse=True)
            top = hits[:limit]
            for i in top:                                # recall reinforces
                i.reinforcement += 0.5
                i.access_count += 1
                i.last_access = time.time()
            return [i.to_dict() for i in top]

    # ── forgetting + consolidation ───────────────────────────────────────────────
    def forget(self, mem_id: str) -> bool:
        with self._lock:
            return self._items.pop(mem_id, None) is not None

    def forget_stale(self, *, now: Optional[float] = None) -> int:
        """Drop low-tier, unreinforced, stale memories (use-it-or-lose-it)."""
        now = now if now is not None else time.time()
        with self._lock:
            stale = [mid for mid, i in self._items.items()
                     if i.tier <= MemoryTier.SHORT_TERM and not i.user_confirmed
                     and now - i.last_access > self._stale_after and i.reinforcement < 1.0]
            for mid in stale:
                self._items.pop(mid, None)
            return len(stale)

    def consolidate(self, summarizer: Optional[Callable[[list], str]] = None,
                    *, min_cluster: int = 3) -> list:
        """Cluster episodic memories by keyword overlap and fold each cluster into one
        semantic memory. Returns the consolidations performed."""
        with self._lock:
            episodic = [i for i in self._items.values() if i.tier == MemoryTier.EPISODIC]
        clusters = _cluster(episodic)
        results = []
        for cluster in clusters:
            if len(cluster) < min_cluster:
                continue
            summary = (summarizer(cluster) if summarizer else
                       "Recurring: " + "; ".join(sorted({c.content for c in cluster}))[:200])
            semantic = self.store(summary, importance=0.7, confidence=0.7, kind="semantic")
            semantic.tier = MemoryTier.SEMANTIC
            with self._lock:
                for c in cluster:
                    self._items.pop(c.mem_id, None)
            results.append({"summary": summary, "merged": len(cluster)})
        return results

    # ── queries / stats ──────────────────────────────────────────────────────────
    def by_tier(self, tier: MemoryTier) -> list:
        with self._lock:
            return [i.to_dict() for i in self._items.values() if i.tier == tier]

    def counts(self) -> dict:
        with self._lock:
            out = {t.label: 0 for t in MemoryTier}
            for i in self._items.values():
                out[i.tier.label] += 1
            out["total"] = len(self._items)
        return out

    def metrics(self) -> dict:
        return {"promotions": self._promotions, **self.counts()}

    # ── internals ────────────────────────────────────────────────────────────────
    def _enforce_working_capacity(self) -> None:
        working = [i for i in self._items.values() if i.tier == MemoryTier.WORKING]
        if len(working) <= self._working_capacity:
            return
        working.sort(key=lambda i: i.last_access)        # evict oldest working memories
        for i in working[: len(working) - self._working_capacity]:
            self._items.pop(i.mem_id, None)


def _cluster(items: list) -> list:
    """Single-link clustering by shared significant tokens."""
    def tokens(text: str) -> set:
        return {w for w in text.lower().split() if len(w) > 3}

    clusters: list = []
    for item in items:
        t = tokens(item.content)
        placed = False
        for c in clusters:
            if t & c["tokens"]:
                c["items"].append(item)
                c["tokens"] |= t
                placed = True
                break
        if not placed:
            clusters.append({"tokens": t, "items": [item]})
    return [c["items"] for c in clusters]
