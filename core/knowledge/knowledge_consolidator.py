"""
core/knowledge/knowledge_consolidator.py — FRIDAY 4.0 (M7)
Keeps the knowledge base lean and coherent. Over time many small, overlapping
entries accumulate on one subject; the consolidator clusters them, writes a
single distilled summary, archives the originals (never deletes — the vault owns
the data), and records lineage so the summary can be traced back.

Clustering is local and category-scoped: entries in the same category whose
titles/contents overlap above a threshold form a cluster. Off the request path;
schedule it on the runtime.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from .knowledge_models import (ConsolidationResult, KnowledgeCategory,
                               KnowledgeEntry, KnowledgeStatus, new_knowledge)

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


Summarizer = Callable[[list[KnowledgeEntry]], str]


def _default_summarizer(entries: list[KnowledgeEntry]) -> str:
    """Concatenate the distinct points into one concise summary. Local, no cloud."""
    seen: set[str] = set()
    lines: list[str] = []
    for e in entries:
        key = e.content.strip()[:80].lower()
        if key and key not in seen:
            seen.add(key)
            lines.append(f"- {e.content.strip()}")
    body = "\n".join(lines)
    return body[:2000]


class KnowledgeConsolidator:
    def __init__(self, store, *, overlap_threshold: float = 0.4,
                 min_cluster: int = 2) -> None:
        self._store = store
        self._threshold = overlap_threshold
        self._min = min_cluster

    def cluster(self, entries: list[KnowledgeEntry]) -> list[list[KnowledgeEntry]]:
        """Greedy single-link clustering by title+content token overlap."""
        clusters: list[list[KnowledgeEntry]] = []
        sigs: list[set[str]] = []
        for e in entries:
            sig = _tokens(e.title) | _tokens(e.content)
            placed = False
            for i, cs in enumerate(sigs):
                if _overlap(sig, cs) >= self._threshold:
                    clusters[i].append(e)
                    sigs[i] = cs | sig
                    placed = True
                    break
            if not placed:
                clusters.append([e])
                sigs.append(sig)
        return clusters

    def consolidate(self, category: Optional[str] = None,
                    summarizer: Optional[Summarizer] = None) -> ConsolidationResult:
        """Cluster active entries (optionally within one category), summarise each
        multi-entry cluster, archive its members, and link summary→sources."""
        summarizer = summarizer or _default_summarizer
        result = ConsolidationResult()
        entries = self._store.list(category=category, status=KnowledgeStatus.ACTIVE.value,
                                   limit=1_000_000)
        for cluster in self.cluster(entries):
            if len(cluster) < self._min:
                continue
            cat = cluster[0].category
            title = self._summary_title(cluster)
            summary_text = summarizer(cluster)
            confidence = min(0.95, max(e.confidence for e in cluster) + 0.05)
            summary = new_knowledge(
                title=title, content=summary_text,
                category=cat if cat != KnowledgeCategory.GENERAL else KnowledgeCategory.SUMMARY,
                confidence=confidence, source="consolidation",
                metadata={"summary": True,
                          "sources": [e.id for e in cluster]},
            )
            self._store.create(summary)
            self._store.add_history(summary.id, "consolidated",
                                    {"sources": [e.id for e in cluster]})
            for e in cluster:
                self._store.set_status(e.id, KnowledgeStatus.ARCHIVED.value)
                self._store.add_history(e.id, "archived", {"into": summary.id})
            result.summaries_created += 1
            result.archived += len(cluster)
            result.summary_ids.append(summary.id)
        return result

    def _summary_title(self, cluster: list[KnowledgeEntry]) -> str:
        base = cluster[0].title.strip()
        base = re.sub(r"\s+", " ", base)
        return f"{base[:80]} (summary)"
