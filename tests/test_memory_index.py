"""
Tests for core/memory/index.py — the rebuildable vector index (numpy backend).
"""

import numpy as np
import pytest

from core.memory import NumpyFlatIndex, build_index


def _unit(*xs) -> np.ndarray:
    v = np.asarray(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def test_add_and_search_ranks_by_cosine():
    idx = NumpyFlatIndex(dim=3)
    idx.add(1, _unit(1, 0, 0))
    idx.add(2, _unit(0, 1, 0))
    idx.add(3, _unit(0.9, 0.1, 0))
    hits = idx.search(_unit(1, 0, 0), k=2)
    ids = [i for i, _ in hits]
    assert ids[0] == 1            # exact match first
    assert ids[1] == 3            # near-parallel second
    assert hits[0][1] >= hits[1][1]


def test_remove_and_size():
    idx = NumpyFlatIndex(dim=2)
    idx.add(10, _unit(1, 0))
    idx.add(20, _unit(0, 1))
    assert idx.size() == 2
    idx.remove(10)
    assert idx.size() == 1
    assert all(i != 10 for i, _ in idx.search(_unit(1, 0), k=5))


def test_reset_and_add_many():
    idx = NumpyFlatIndex(dim=2)
    idx.add_many([1, 2], np.asarray([_unit(1, 0), _unit(0, 1)]))
    assert idx.size() == 2
    idx.reset()
    assert idx.size() == 0
    assert idx.search(_unit(1, 0), k=1) == []


def test_empty_search_returns_empty():
    assert NumpyFlatIndex(dim=4).search(_unit(1, 0, 0, 0), k=3) == []


def test_build_index_returns_working_backend():
    idx = build_index(dim=8)
    assert hasattr(idx, "backend")
    idx.add(1, _unit(*([1] + [0] * 7)))
    assert idx.size() == 1
