"""
core/knowledge/documentation_service.py — FRIDAY 4.0 (M7)
The only sanctioned bridge to *external* knowledge — and it is deliberately the
last resort.

Hard rules (from the M7 charter):
  • Never search externally first. Always search local knowledge last-resort only.
  • External information must be SUMMARISED before storage.
  • Never store entire pages. Store only distilled conclusions.
  • Fully optional/offline by default: the external fetcher is injected and is
    None unless the caller explicitly provides one. With no fetcher, the service
    answers purely from local knowledge.

Lookup order: local store text search → (only if insufficient) external fetch →
summarise → hand the distilled conclusion back for validated storage.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from .knowledge_models import KnowledgeCategory, KnowledgeEntry, new_knowledge

log = logging.getLogger("friday.knowledge.docs")

# A fetcher takes a query and returns raw external text (or None). Injected by the
# caller; the service never reaches the network on its own.
Fetcher = Callable[[str], Optional[str]]

_SENT = re.compile(r"(?<=[.!?])\s+")


def summarize(text: str, *, max_sentences: int = 3, max_chars: int = 600) -> str:
    """Distil raw text to a few high-signal sentences. Deterministic, local —
    NOT a page dump. Picks the longest (most informative) sentences in order."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    sentences = [s.strip() for s in _SENT.split(raw) if len(s.strip()) > 20]
    if not sentences:
        return raw[:max_chars]
    ranked = sorted(enumerate(sentences), key=lambda it: (-len(it[1]), it[0]))
    keep = sorted(i for i, _ in ranked[:max_sentences])
    summary = " ".join(sentences[i] for i in keep)
    return summary[:max_chars]


class DocumentationService:
    def __init__(self, store, *, fetcher: Optional[Fetcher] = None,
                 sufficiency: int = 1) -> None:
        self._store = store
        self._fetcher = fetcher              # None ⇒ fully offline
        self._sufficiency = sufficiency      # local hits needed to skip external

    @property
    def can_fetch(self) -> bool:
        return self._fetcher is not None

    def local_lookup(self, query: str, k: int = 5) -> list[KnowledgeEntry]:
        return self._store.search_text(query, limit=k)

    def lookup(self, query: str, *, category: str = KnowledgeCategory.GENERAL,
               k: int = 5) -> dict:
        """Resolve a query local-first. Returns:
            {source: 'local'|'external'|'none', entries: [...], candidate: KnowledgeEntry|None}
        `candidate` is a distilled, UNSTORED entry the caller can validate+store."""
        local = self.local_lookup(query, k=k)
        if len(local) >= self._sufficiency:
            return {"source": "local", "entries": local, "candidate": None}

        # local knowledge insufficient → fall back to external, only if allowed
        if not self.can_fetch:
            return {"source": "none", "entries": local, "candidate": None}

        raw = None
        try:
            raw = self._fetcher(query)
        except Exception as e:                  # external faults never crash FRIDAY
            log.warning("external fetch failed for %r: %s", query, e)
        if not raw:
            return {"source": "none", "entries": local, "candidate": None}

        distilled = summarize(raw)
        if not distilled:
            return {"source": "none", "entries": local, "candidate": None}

        candidate = new_knowledge(
            title=query.strip()[:120], content=distilled, category=category,
            confidence=0.4, source="external",
            metadata={"external": True, "summarized": True},
        )
        return {"source": "external", "entries": local, "candidate": candidate}
