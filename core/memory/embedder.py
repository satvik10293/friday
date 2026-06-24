"""
core/memory/embedder.py — FRIDAY 4.0
Pluggable text embedders. Production uses MiniLM; a deterministic hashing
embedder is the dependency-free fallback (and what the tests inject) so the
Memory Service is fully testable without heavy ML deps.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import re
from typing import Protocol, runtime_checkable

import numpy as np

log = logging.getLogger("friday.memory.embedder")

_TOKEN = re.compile(r"[a-z0-9]+")


@runtime_checkable
class Embedder(Protocol):
    dim: int
    backend: str
    def encode(self, text: str) -> np.ndarray: ...


class HashingEmbedder:
    """Deterministic bag-of-words hashing embedder. No external deps.
    Stable across processes (md5-based), so a persisted index stays valid."""

    backend = "hashing"

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @staticmethod
    def _bucket(tok: str, dim: int) -> int:
        return int.from_bytes(hashlib.md5(tok.encode()).digest()[:4], "little") % dim

    def encode(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in _TOKEN.findall((text or "").lower()):
            v[self._bucket(tok, self.dim)] += 1.0
        n = float(np.linalg.norm(v))
        if n > 0:
            v /= n
        return v


class MiniLMEmbedder:
    """sentence-transformers all-MiniLM-L6-v2 (lazy-loaded, CPU-friendly)."""

    backend = "minilm"
    dim = 384

    def __init__(self) -> None:
        self._model = None

    def _get(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            log.info("loading embedding model all-MiniLM-L6-v2")
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
        return self._model

    def encode(self, text: str) -> np.ndarray:
        vec = self._get().encode([(text or "")[:512]], normalize_embeddings=True)[0]
        return np.asarray(vec, dtype=np.float32)


def get_embedder() -> Embedder:
    """Pick the best available embedder without loading the heavy model."""
    if importlib.util.find_spec("sentence_transformers") is not None:
        return MiniLMEmbedder()
    log.warning("sentence-transformers not installed — using hashing embedder")
    return HashingEmbedder()
