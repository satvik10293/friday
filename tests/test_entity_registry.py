"""M13 — Persistent Entity Registry + repositories (SQLite + in-memory)."""

import pytest

from core.cognition_core.entity_registry import PersistentEntityRegistry
from core.cognition_core.repositories import (InMemoryEntityRepository,
                                              SqliteEntityRepository)


@pytest.fixture(params=["memory", "sqlite"])
def repo(request, tmp_path):
    if request.param == "memory":
        yield InMemoryEntityRepository()
    else:
        r = SqliteEntityRepository(path=tmp_path / "cognition.db")
        try:
            yield r
        finally:
            r.close()


def test_opaque_stable_ids(repo):
    reg = PersistentEntityRegistry(repo)
    a = reg.create("device", "Webcam")
    b = reg.create("device", "Mic")
    assert a.stable_id == "ENT_000001" and b.stable_id == "ENT_000002"
    assert a.stable_id != a.kind and "Webcam" not in a.stable_id      # opaque


def test_get_and_by_kind(repo):
    reg = PersistentEntityRegistry(repo)
    e = reg.create("person", "Satvik")
    assert reg.get(e.stable_id).primary_label == "Satvik"
    assert len(reg.by_kind("person")) == 1


def test_alias_registered_on_create(repo):
    reg = PersistentEntityRegistry(repo)
    e = reg.create("application", "Chrome")
    assert reg.resolve_alias("chrome", "application") == e.stable_id


def test_add_alias_and_label(repo):
    reg = PersistentEntityRegistry(repo)
    e = reg.create("application", "Chrome")
    reg.add_alias(e.stable_id, "Google Chrome")
    assert reg.resolve_alias("google chrome", "application") == e.stable_id
    assert "Google Chrome" in reg.get(e.stable_id).labels


def test_reinforce_updates_attributes(repo):
    reg = PersistentEntityRegistry(repo)
    e = reg.create("device", "Webcam", confidence=0.5)
    reg.reinforce(e.stable_id, attributes={"resolution": "1080p"}, confidence=0.9)
    fresh = reg.get(e.stable_id)
    assert fresh.attributes["resolution"] == "1080p" and fresh.confidence == 0.9


def test_merge_folds_entities(repo):
    reg = PersistentEntityRegistry(repo)
    keep = reg.create("person", "Sat", attributes={"a": 1})
    drop = reg.create("person", "Satvik", attributes={"b": 2})
    reg.add_alias(drop.stable_id, "satvik rao")
    merged = reg.merge(keep.stable_id, drop.stable_id)
    assert merged.stable_id == keep.stable_id                # kept id is permanent
    assert "Satvik" in merged.labels
    assert merged.attributes == {"a": 1, "b": 2}
    assert drop.stable_id in merged.merged_from
    assert reg.get(drop.stable_id) is None                   # dropped id removed
    # the dropped entity's alias now resolves to the kept id
    assert reg.resolve_alias("satvik rao", "person") == keep.stable_id


def test_merge_same_id_noop(repo):
    reg = PersistentEntityRegistry(repo)
    e = reg.create("device", "X")
    assert reg.merge(e.stable_id, e.stable_id).stable_id == e.stable_id


def test_sqlite_persistence(tmp_path):
    r1 = SqliteEntityRepository(path=tmp_path / "c.db")
    reg1 = PersistentEntityRegistry(r1)
    sid = reg1.create("person", "Satvik").stable_id
    r1.close()
    r2 = SqliteEntityRepository(path=tmp_path / "c.db")
    assert PersistentEntityRegistry(r2).get(sid).primary_label == "Satvik"
    r2.close()


def test_sqlite_id_counter_persists(tmp_path):
    r1 = SqliteEntityRepository(path=tmp_path / "c.db")
    PersistentEntityRegistry(r1).create("a", "1")
    r1.close()
    r2 = SqliteEntityRepository(path=tmp_path / "c.db")
    second = PersistentEntityRegistry(r2).create("a", "2")
    assert second.stable_id == "ENT_000002"                  # counter survived restart
    r2.close()
