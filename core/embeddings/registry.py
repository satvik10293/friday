"""
core/embeddings/registry.py — FRIDAY 4.0 (M10)
The embedding abstraction layer. No embedding model is hardcoded: callers ask the
registry for a backend by name (or let it auto-select the best available), and the
registry constructs it lazily. Heavy ML libraries are imported only when a model is
actually built — importing this module never loads a model.

Built-in backends:
  • hashing    — deterministic, dependency-free (always available; the safe default)
  • minilm     — sentence-transformers all-MiniLM-L6-v2        (384-d)
  • bge-small  — sentence-transformers BAAI/bge-small-en-v1.5  (384-d)
  • nomic      — sentence-transformers nomic-ai/nomic-embed-text-v1 (768-d)

New backends register without touching call sites — `EmbeddingRegistry.register`.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from typing import Callable, Optional, Protocol, runtime_checkable

import numpy as np

log = logging.getLogger("friday.embeddings.registry")


@runtime_checkable
class EmbeddingBackend(Protocol):
    name: str
    dim: int
    def encode(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Generic sentence-transformers backend (lazy-loaded, CPU-friendly,
    normalized output). Used for MiniLM / BGE / Nomic by model id."""

    def __init__(self, name: str, model_id: str, dim: int) -> None:
        self.name = name
        self.model_id = model_id
        self.dim = dim
        self._model = None

    def _get(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            log.info("loading embedding model %s", self.model_id)
            self._model = SentenceTransformer(self.model_id, trust_remote_code=True)
        return self._model

    def encode(self, text: str) -> np.ndarray:
        vec = self._get().encode([(text or "")[:512]], normalize_embeddings=True)[0]
        return np.asarray(vec, dtype=np.float32)


# name -> (factory, requires_sentence_transformers)
def _hashing_factory() -> EmbeddingBackend:
    from core.memory.embedder import HashingEmbedder
    emb = HashingEmbedder()
    emb.name = "hashing"            # satisfy the protocol's `name`
    return emb


_BUILTINS: dict[str, dict] = {
    "hashing": {"factory": _hashing_factory, "needs_st": False, "dim": 256},
    "minilm": {"model_id": "sentence-transformers/all-MiniLM-L6-v2",
               "needs_st": True, "dim": 384},
    "bge-small": {"model_id": "BAAI/bge-small-en-v1.5", "needs_st": True, "dim": 384},
    "nomic": {"model_id": "nomic-ai/nomic-embed-text-v1", "needs_st": True, "dim": 768},
}


def _has_sentence_transformers() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


class EmbeddingRegistry:
    def __init__(self) -> None:
        self._custom: dict[str, Callable[[], EmbeddingBackend]] = {}

    def register(self, name: str, factory: Callable[[], EmbeddingBackend]) -> None:
        self._custom[name] = factory

    def names(self) -> list[str]:
        return sorted(set(_BUILTINS) | set(self._custom))

    def available(self) -> list[str]:
        """Backends that can actually be constructed right now (hashing always;
        ST backends only if sentence-transformers is installed)."""
        st = _has_sentence_transformers()
        out = list(self._custom)
        for name, spec in _BUILTINS.items():
            if not spec.get("needs_st") or st:
                out.append(name)
        return sorted(set(out))

    def create(self, name: Optional[str] = None) -> EmbeddingBackend:
        """Construct a backend. With no name, auto-selects the best available.
        Falls back to hashing (with a warning) if a requested ST model can't load."""
        if name is None:
            name = self.best_available()
        if name in self._custom:
            return self._custom[name]()
        spec = _BUILTINS.get(name)
        if spec is None:
            log.warning("unknown embedding backend %r — using hashing", name)
            return _hashing_factory()
        if not spec.get("needs_st"):
            return spec["factory"]()
        if not _has_sentence_transformers():
            log.warning("sentence-transformers not installed — '%s' falls back to hashing", name)
            return _hashing_factory()
        return SentenceTransformerEmbedder(name, spec["model_id"], spec["dim"])

    def best_available(self) -> str:
        """Preference order when nothing is specified. Quality first, then the
        guaranteed fallback."""
        if _has_sentence_transformers():
            for preferred in ("bge-small", "minilm", "nomic"):
                if preferred in self.available():
                    return preferred
        return "hashing"


_registry = EmbeddingRegistry()


def resolve_backend_name(explicit: Optional[str] = None) -> str:
    """Resolve which backend to use: explicit arg > FRIDAY_EMBEDDING_MODEL env >
    auto-selected best available. Never a hardcoded literal at a call site."""
    return explicit or os.environ.get("FRIDAY_EMBEDDING_MODEL") or _registry.best_available()


def get_embedding_backend(name: Optional[str] = None) -> EmbeddingBackend:
    return _registry.create(resolve_backend_name(name))


def available_backends() -> list[str]:
    return _registry.available()
