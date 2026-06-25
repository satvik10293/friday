"""
core/retrieval/ — FRIDAY 4.0 (M10)
Hardened retrieval pipeline + metrics, built on the pluggable embedding layer
(core.embeddings). Implements the full local-first cascade —
Working Memory → Memory → Knowledge DB → Semantic Search → Knowledge Graph →
External — with measurable quality (accuracy, latency, confidence).

Additive: composes the M7/M8 knowledge service and M2 memory by injection; does not
modify them. Side-effect-free to import.
"""

from __future__ import annotations

from .metrics import RetrievalMetrics
from .semantic_search import SemanticSearch, SemanticSearchResult

__all__ = ["SemanticSearch", "SemanticSearchResult", "RetrievalMetrics"]
