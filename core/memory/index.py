"""
core/memory/index.py — FRIDAY 4.0
The derived vector index. NOT a source of truth — fully rebuildable from the
MemoryStore at any time. Two backends:

  • FaissHNSWIndex  — approximate nearest-neighbour (HNSW, inner-product on
                      normalized vectors = cosine). Scales to millions.
  • NumpyFlatIndex  — exact brute force, dependency-light fallback / test backend.

Vectors are keyed by the memory's SQLite id (the in-row `embed_id`), so the
index can always be reconstructed from the store — the fix for the 3.0
"save-every-20 side-list desync".
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Protocol

import numpy as np

log = logging.getLogger("friday.memory.index")


class VectorIndex(Protocol):
    backend: str
    def add(self, id: int, vec: np.ndarray) -> None: ...
    def add_many(self, ids: list[int], vecs: np.ndarray) -> None: ...
    def search(self, vec: np.ndarray, k: int) -> list[tuple[int, float]]: ...
    def remove(self, id: int) -> None: ...
    def reset(self) -> None: ...
    def size(self) -> int: ...


class NumpyFlatIndex:
    """Exact cosine index. Assumes normalized vectors (cosine == dot)."""

    backend = "numpy-flat"

    def __init__(self, dim: int) -> None:
        self.dim = dim
        self._ids: list[int] = []
        self._mat = np.zeros((0, dim), dtype=np.float32)

    def add(self, id: int, vec: np.ndarray) -> None:
        self._ids.append(int(id))
        self._mat = np.vstack([self._mat, np.asarray(vec, dtype=np.float32).reshape(1, -1)])

    def add_many(self, ids: list[int], vecs: np.ndarray) -> None:
        if not ids:
            return
        self._ids.extend(int(i) for i in ids)
        self._mat = np.vstack([self._mat, np.asarray(vecs, dtype=np.float32)])

    def search(self, vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._mat.shape[0] == 0:
            return []
        q = np.asarray(vec, dtype=np.float32)
        sims = self._mat @ q
        k = min(k, len(self._ids))
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        return [(self._ids[i], float(sims[i])) for i in idx]

    def remove(self, id: int) -> None:
        try:
            pos = self._ids.index(int(id))
        except ValueError:
            return
        del self._ids[pos]
        self._mat = np.delete(self._mat, pos, axis=0)

    def reset(self) -> None:
        self._ids = []
        self._mat = np.zeros((0, self.dim), dtype=np.float32)

    def size(self) -> int:
        return len(self._ids)


class FaissHNSWIndex:
    """HNSW ANN index keyed by memory id (via IndexIDMap2)."""

    backend = "faiss-hnsw"

    def __init__(self, dim: int, M: int = 32) -> None:
        import faiss
        self._faiss = faiss
        self.dim = dim
        self._M = M
        self._index = self._new()

    def _new(self):
        base = self._faiss.IndexHNSWFlat(self.dim, self._M, self._faiss.METRIC_INNER_PRODUCT)
        return self._faiss.IndexIDMap2(base)

    def add(self, id: int, vec: np.ndarray) -> None:
        self._index.add_with_ids(
            np.asarray(vec, dtype="float32").reshape(1, -1),
            np.asarray([id], dtype="int64"),
        )

    def add_many(self, ids: list[int], vecs: np.ndarray) -> None:
        if len(ids) == 0:
            return
        self._index.add_with_ids(
            np.asarray(vecs, dtype="float32"),
            np.asarray(ids, dtype="int64"),
        )

    def search(self, vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        if self._index.ntotal == 0:
            return []
        D, I = self._index.search(
            np.asarray(vec, dtype="float32").reshape(1, -1), min(k, self._index.ntotal)
        )
        return [(int(i), float(d)) for i, d in zip(I[0], D[0]) if i != -1]

    def remove(self, id: int) -> None:
        # HNSW does not support deletion; the service handles forgetting via
        # store-side soft-delete + recall-time filtering + periodic rebuild.
        raise NotImplementedError("HNSW removal unsupported; rebuild the index")

    def reset(self) -> None:
        self._index = self._new()

    def size(self) -> int:
        return int(self._index.ntotal)


def build_index(dim: int) -> VectorIndex:
    """Pick the best available ANN backend; fall back to exact numpy."""
    if importlib.util.find_spec("faiss") is not None:
        try:
            return FaissHNSWIndex(dim)
        except Exception as e:
            log.warning("faiss unavailable (%s) — using numpy flat index", e)
    return NumpyFlatIndex(dim)
