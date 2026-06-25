"""
core/embeddings/ — FRIDAY 4.0 (M10)
Pluggable embedding abstraction. Closes the architecture review's "knowledge search
is keyword-only / embedder hardcoded" risk: a registry resolves embedding backends
by name (BGE-Small, MiniLM, Nomic Embed, hashing fallback) with no model hardwired
anywhere. Backends are lazily loaded, so importing this package is cheap and
dependency-light.

Side-effect-free to import.
"""

from __future__ import annotations

from .registry import (EmbeddingBackend, EmbeddingRegistry, available_backends,
                       get_embedding_backend, resolve_backend_name)

__all__ = ["EmbeddingBackend", "EmbeddingRegistry", "get_embedding_backend",
           "available_backends", "resolve_backend_name"]
