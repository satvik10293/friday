"""
core/retrieval/semantic_search.py — FRIDAY 4.0 (M10)
The hardened retrieval pipeline. Runs the full local-first cascade and ranks
knowledge with real vector similarity from the pluggable embedding layer (not the
keyword-only path the architecture review flagged), measuring quality as it goes.

Cascade:  Working Memory → Memory → Knowledge DB → Semantic Search → Knowledge
Graph → External (last resort, opt-in only).

Additive: composes the injected M7/M8 KnowledgeService and M2 MemoryService.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from core.embeddings.registry import get_embedding_backend
from .metrics import RetrievalMetrics

log = logging.getLogger("friday.retrieval.semantic")


@dataclass
class SemanticSearchResult:
    query: str = ""
    source: str = "none"          # working|memory|knowledge|semantic|graph|external|none
    items: list = field(default_factory=list)
    related: list = field(default_factory=list)
    confidence: float = 0.0
    latency_ms: float = 0.0
    backend: str = ""
    trace: list = field(default_factory=list)
    external_candidate: Optional[object] = None

    @property
    def found(self) -> bool:
        return bool(self.items)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        if self.external_candidate is not None and hasattr(self.external_candidate, "to_dict"):
            d["external_candidate"] = self.external_candidate.to_dict()
        return d


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SemanticSearch:
    def __init__(self, knowledge_service=None, *, embedder=None, memory_service=None,
                 threshold: float = 0.5, metrics: Optional[RetrievalMetrics] = None) -> None:
        self._k = knowledge_service
        self._mem = memory_service
        self._embedder = embedder if embedder is not None else get_embedding_backend()
        self._threshold = threshold
        self.metrics = metrics if metrics is not None else RetrievalMetrics()
        self._cache: dict[str, tuple[float, np.ndarray]] = {}   # id -> (updated_at, vec)

    @property
    def backend(self) -> str:
        return getattr(self._embedder, "name", getattr(self._embedder, "backend", "unknown"))

    # ── embedding (cached per entry) ────────────────────────────────────────────
    def _vec(self, key: str, text: str, version: float = 0.0) -> np.ndarray:
        cached = self._cache.get(key)
        if cached is not None and cached[0] == version:
            return cached[1]
        vec = self._embedder.encode(text)
        self._cache[key] = (version, vec)
        return vec

    def semantic_rank(self, query: str, entries: list, k: int) -> list[tuple]:
        """Rank knowledge entries by vector cosine to the query."""
        if not entries:
            return []
        qv = self._embedder.encode(query)
        scored = []
        for e in entries:
            ev = self._vec(e.id, f"{e.title}\n{e.content}", getattr(e, "updated_at", 0.0))
            scored.append((e, _cosine(qv, ev)))
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    # ── pipeline ────────────────────────────────────────────────────────────────
    def search(self, query: str, *, k: int = 5,
               allow_external: bool = False) -> SemanticSearchResult:
        t0 = time.perf_counter()
        res = SemanticSearchResult(query=query, backend=self.backend)

        # 1) working memory
        res.trace.append("working")
        for item in self._working(query):
            res.items.append(item)
        if res.items:
            res.source = "working"
            res.confidence = 0.6
            return self._finish(res, t0)

        # 2) memory service
        res.trace.append("memory")
        mem = self._memory(query, k)
        if mem:
            res.items = mem
            res.source = "memory"
            res.confidence = 0.55
            return self._finish(res, t0)

        # 3) knowledge DB (keyword) + 4) semantic re-rank
        res.trace.append("knowledge")
        if self._k is not None:
            active = self._k.store.all_entries(status="active")
            res.trace.append("semantic")
            ranked = self.semantic_rank(query, active, k)
            if ranked and ranked[0][1] > 0:
                res.items = [{**e.to_dict(), "score": round(s, 4)} for e, s in ranked]
                res.source = "semantic"
                res.confidence = ranked[0][1]
                # 5) knowledge graph neighbours of the top hit
                res.trace.append("graph")
                res.related = self._graph(ranked[0][0].id)
                if res.confidence >= self._threshold:
                    return self._finish(res, t0)

        # 6) external (last resort, opt-in)
        if res.confidence < self._threshold and allow_external and self._k is not None:
            res.trace.append("external")
            ext = self._k.answer(query, k=k, allow_external=True)
            if ext.get("source") == "external" and ext.get("candidate") is not None:
                res.source = "external"
                res.external_candidate = ext["candidate"]
                res.confidence = ext["candidate"].confidence
        return self._finish(res, t0)

    def _finish(self, res: SemanticSearchResult, t0: float) -> SemanticSearchResult:
        res.latency_ms = (time.perf_counter() - t0) * 1000.0
        top = res.confidence
        self.metrics.record_search(latency_ms=res.latency_ms, confidence=res.confidence,
                                   top_score=top, hit=res.found)
        return res

    # ── tiers ───────────────────────────────────────────────────────────────────
    def _working(self, query: str) -> list[dict]:
        if self._mem is None:
            return []
        terms = {w for w in query.lower().split() if len(w) > 2}
        out = []
        for item in self._mem.working().snapshot():
            if terms and any(t in str(item.get("content", "")).lower() for t in terms):
                out.append({**item, "tier": "working"})
        return out

    def _memory(self, query: str, k: int) -> list[dict]:
        if self._mem is None:
            return []
        rows = self._mem.recall(query, k=k)
        for r in rows:
            r["tier"] = "memory"
        return rows

    def _graph(self, kid: str) -> list[dict]:
        out = []
        try:
            for nid in self._k.graph.neighbors(kid)[:5]:
                e = self._k.store.get(nid)
                if e is not None:
                    out.append({"id": e.id, "title": e.title, "category": e.category})
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        return out

    # ── evaluation ──────────────────────────────────────────────────────────────
    def evaluate(self, query: str, relevant_ids: list[str], *, k: int = 5) -> float:
        """Precision@k against a known-relevant set; also records it in metrics."""
        res = self.search(query, k=k)
        got = [it.get("id") for it in res.items][:k]
        if not got:
            p = 0.0
        else:
            p = sum(1 for g in got if g in set(relevant_ids)) / len(got)
        self.metrics.record_accuracy(p)
        return p

    def health(self) -> dict:
        return {"status": "ok", "backend": self.backend,
                "metrics": self.metrics.snapshot()}
