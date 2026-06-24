"""Tests for the M7 KnowledgeIndex (semantic retrieval cache)."""

from core.knowledge.knowledge_index import KnowledgeIndex


def test_add_and_search():
    idx = KnowledgeIndex()
    idx.add("k1", "flask template not found error")
    idx.add("k2", "sqlite connection per thread")
    hits = idx.search("template error in flask", k=2)
    assert hits and hits[0][0] == "k1"


def test_empty_search():
    assert KnowledgeIndex().search("anything") == []


def test_size_tracks_entries():
    idx = KnowledgeIndex()
    idx.add("a", "x"); idx.add("b", "y")
    assert idx.size() == 2


def test_readd_replaces():
    idx = KnowledgeIndex()
    idx.add("a", "first text alpha")
    idx.add("a", "second text beta")
    assert idx.size() == 1


def test_remove():
    idx = KnowledgeIndex()
    idx.add("a", "alpha"); idx.add("b", "beta")
    idx.remove("a")
    assert idx.size() == 1
    ids = [sid for sid, _ in idx.search("alpha", k=5)]
    assert "a" not in ids


def test_remove_unknown_noop():
    idx = KnowledgeIndex()
    idx.remove("ghost")          # must not raise
    assert idx.size() == 0


def test_rebuild():
    idx = KnowledgeIndex()
    idx.add("old", "stale")
    n = idx.rebuild([("a", "alpha one"), ("b", "beta two"), ("c", "gamma three")])
    assert n == 3 and idx.size() == 3
    ids = {sid for sid, _ in idx.search("beta", k=3)}
    assert "b" in ids and "old" not in ids


def test_reset():
    idx = KnowledgeIndex()
    idx.add("a", "x")
    idx.reset()
    assert idx.size() == 0 and idx.search("x") == []


def test_health():
    idx = KnowledgeIndex()
    idx.add("a", "x")
    h = idx.health()
    assert h["status"] == "ok" and h["vectors"] == 1 and h["dim"] > 0


def test_str_int_mapping_stable_after_remove():
    idx = KnowledgeIndex()
    idx.add("a", "alpha"); idx.add("b", "beta")
    idx.remove("a")
    idx.add("c", "gamma")
    found = {sid for sid, _ in idx.search("gamma", k=3)}
    assert "c" in found
