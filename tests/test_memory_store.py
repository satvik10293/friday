"""
Tests for core/memory/store.py — the SQLite source of truth.
Covers: CRUD, keyword search (FTS or LIKE), soft-delete exclusion, supersede
lineage, tiers, counts, per-thread connections, and migration bookkeeping.
"""

import threading

import pytest

from core.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(path=tmp_path / "mem.db")
    yield s
    s.close()


def test_insert_and_get(store):
    mid = store.insert("user", "I am building Friday", topic="friday", importance=0.9)
    row = store.get(mid)
    assert row["content"] == "I am building Friday"
    assert row["tier"] == "episodic"
    assert row["deleted"] is False
    assert row["metadata"] == {}


def test_keyword_search_finds_and_filters_deleted(store):
    a = store.insert("user", "python is a programming language", topic="python")
    store.insert("user", "the cat sat on the mat", topic="animals")
    hits = store.keyword_search("python")
    assert any(h["id"] == a for h in hits)
    store.soft_delete(a)
    hits2 = store.keyword_search("python")
    assert all(h["id"] != a for h in hits2)


def test_by_ids_excludes_deleted_by_default(store):
    a = store.insert("user", "alpha")
    b = store.insert("user", "beta")
    store.soft_delete(b)
    rows = store.by_ids([a, b])
    ids = {r["id"] for r in rows}
    assert ids == {a}
    assert {r["id"] for r in store.by_ids([a, b], include_deleted=True)} == {a, b}


def test_supersede_lineage(store):
    old = store.insert("user", "the sky is green")
    new = store.insert("user", "the sky is blue")
    store.set_superseded(old, new)
    o = store.get(old)
    assert o["deleted"] is True
    assert o["superseded_by"] == new


def test_tiers_and_counts(store):
    a = store.insert("user", "one")
    b = store.insert("user", "two")
    store.update_tier(b, "archival")
    c = store.counts()
    assert c["episodic"] == 1
    assert c["archival"] == 1
    assert c["total"] == 2
    with pytest.raises(ValueError):
        store.update_tier(a, "nonsense")


def test_touch_increments_access(store):
    a = store.insert("user", "touch me")
    store.touch(a)
    store.touch(a)
    assert store.get(a)["access_count"] == 2


def test_per_thread_connection_writes(store):
    """A write from another thread must succeed (3.0 used one shared conn with an
    unused lock; the new store uses per-thread connections + WAL)."""
    ids = []

    def worker():
        ids.append(store.insert("user", "from another thread"))

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert len(ids) == 1
    assert store.get(ids[0]) is not None


def test_import_bookkeeping(store):
    assert store.import_done("chronicle") is False
    store.mark_import("chronicle")
    assert store.import_done("chronicle") is True
