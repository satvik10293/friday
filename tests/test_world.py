"""
tests/test_world.py — FRIDAY 4.0 M5
World Model: entity CRUD, observation merge, relationships, snapshots + diff,
restore, persistence/recovery, health.
"""

import pytest

from core.world import (
    WorldModel, WorldEntity, WorldRelationship, new_entity, diff_snapshots,
)


@pytest.fixture
def world(tmp_path):
    wm = WorldModel(path=tmp_path / "world.db")
    try:
        yield wm
    finally:
        wm.close()


# ── entities ─────────────────────────────────────────────────────────────────
def test_new_entity_deterministic_id_and_clamp():
    e = new_entity("project", "Friday", confidence=2.0)
    assert e.entity_id == "project:Friday"
    assert e.confidence == 1.0


def test_entity_roundtrip():
    e = new_entity("user", "Satvik", state={"mood": "focused"}, attributes={"os": "windows"})
    restored = WorldEntity.from_dict(e.to_dict())
    assert restored.entity_id == e.entity_id
    assert restored.state == {"mood": "focused"}
    assert restored.attributes == {"os": "windows"}


def test_world_crud(world):
    e = new_entity("system", "cpu", state={"load": 0.2})
    world.update_entity(e)
    got = world.get_entity("system:cpu")
    assert got is not None and got.state["load"] == 0.2

    world.remove_entity("system:cpu")
    assert world.get_entity("system:cpu") is None


def test_observe_merges_state(world):
    world.observe("user", "Satvik", state={"focus": "M5"})
    world.observe("user", "Satvik", state={"mood": "good"})
    e = world.get_entity("user:Satvik")
    assert e.state == {"focus": "M5", "mood": "good"}   # merged, not clobbered


def test_entities_by_kind(world):
    world.observe("project", "A")
    world.observe("project", "B")
    world.observe("system", "cpu")
    assert {e.name for e in world.entities_by_kind("project")} == {"A", "B"}


# ── relationships ────────────────────────────────────────────────────────────
def test_relationships(world):
    world.observe("user", "Satvik")
    world.observe("project", "Friday")
    world.add_relationship(WorldRelationship("user:Satvik", "project:Friday", "owns"))
    rels = world.relationships_for("user:Satvik")
    assert len(rels) == 1 and rels[0].kind == "owns"


# ── snapshots ────────────────────────────────────────────────────────────────
def test_snapshot_and_diff(world):
    world.observe("project", "Friday", state={"phase": "M5"})
    before = world.snapshot("before")
    world.observe("project", "Friday", state={"phase": "M6"})
    world.observe("system", "gpu", state={"present": False})
    d = world.compare(before)
    assert "system:gpu" in d["added"]
    assert "project:Friday" in d["changed"]
    assert "state.phase" in d["changed"]["project:Friday"]


def test_diff_detects_removal():
    from core.world import new_snapshot
    a = new_snapshot({"x": new_entity("k", "x").to_dict()}, [])
    b = new_snapshot({}, [])
    d = diff_snapshots(a, b)
    assert d["removed"] == ["x"] and d["added"] == []


def test_restore_replaces_state(world):
    world.observe("project", "Friday", state={"phase": "M5"})
    snap = world.snapshot()
    world.observe("project", "Friday", state={"phase": "M9"})
    world.observe("junk", "temp")
    n = world.restore(snap)
    assert n == 1
    assert world.get_entity("project:Friday").state["phase"] == "M5"
    assert world.get_entity("junk:temp") is None


# ── persistence / health ─────────────────────────────────────────────────────
def test_world_survives_restart(tmp_path):
    db = tmp_path / "persist_world.db"
    wm1 = WorldModel(path=db)
    wm1.observe("project", "Friday", state={"phase": "M5"})
    wm1.close()

    wm2 = WorldModel(path=db)
    e = wm2.get_entity("project:Friday")
    assert e is not None and e.state["phase"] == "M5"
    wm2.close()


def test_health_reports_counts(world):
    world.observe("user", "Satvik")
    h = world.health()
    assert h["status"] == "ok" and h["entities"] == 1 and h["observations"] >= 1
