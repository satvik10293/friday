"""
core/knowledge/executive_bridge.py — FRIDAY 4.0 (M8)
The seam between the M5 Executive Brain and the knowledge system. Lets the brain
search knowledge, store knowledge, and fold knowledge into the ContextPackage it
reasons over — without modifying any M5 file.

Usage (additive, by composition):

    bridge = ExecutiveKnowledgeBridge(knowledge_service, memory_service)
    frag = bridge.build_context("how do flask templates work")
    bridge.augment_context(context_package, "how do flask templates work")
"""

from __future__ import annotations

from typing import Optional

from .knowledge_models import KnowledgeCategory
from .knowledge_search import KnowledgeSearch, SearchTier


class ExecutiveKnowledgeBridge:
    def __init__(self, knowledge_service, memory_service=None, *,
                 threshold: float = 0.5, k: int = 5) -> None:
        self._k = knowledge_service
        self._search = KnowledgeSearch(knowledge_service, memory_service,
                                       threshold=threshold, k=k)

    # ── Executive Brain → Search Knowledge ──────────────────────────────────────
    def search_knowledge(self, query: str, *, k: Optional[int] = None,
                         allow_external: bool = False):
        return self._search.search(query, k=k, allow_external=allow_external)

    # ── Executive Brain → Store Knowledge ───────────────────────────────────────
    def store_knowledge(self, title: str, content: str, *,
                        category: str = KnowledgeCategory.GENERAL,
                        confidence: float = 0.6, source: str = "executive"):
        return self._k.remember_knowledge(
            title, content, category=category, confidence=confidence, source=source)

    # ── Executive Brain → Build Context From Knowledge ──────────────────────────
    def build_context(self, query: str, *, k: int = 5) -> dict:
        """Return a knowledge fragment for ContextPackage construction:
            {knowledge: [...], related: [...], source: tier, confidence: float}"""
        result = self._search.search(query, k=k, allow_external=False)
        knowledge = result.items if result.tier in (
            SearchTier.KNOWLEDGE.value, SearchTier.GRAPH.value) else []
        if not knowledge:
            # always offer distilled knowledge even when a higher tier answered
            knowledge = [e.to_dict() for e in self._k.search_knowledge(query, k=k)]
        return {"knowledge": knowledge, "related": result.related,
                "source": result.tier, "confidence": result.confidence}

    def augment_context(self, context_package, query: str, *, k: int = 5):
        """Attach knowledge to an existing M5 ContextPackage (additively, via its
        public dict-list fields). Stores the fragment under `world['knowledge']`
        and merges distilled lessons into `lessons` so the Reasoner sees them."""
        frag = self.build_context(query, k=k)
        world = dict(getattr(context_package, "world", {}) or {})
        world["knowledge"] = frag
        context_package.world = world
        for item in frag["knowledge"]:
            context_package.lessons.append({
                "source": "knowledge", "title": item.get("title"),
                "content": item.get("content"), "confidence": item.get("confidence"),
            })
        if frag["confidence"] > context_package.confidence:
            context_package.confidence = frag["confidence"]
        return context_package
