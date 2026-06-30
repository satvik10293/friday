"""M16 — Scene Graph: rooms + object nodes, reparenting, relationships, lifecycle,
pruning, persistence (save/load recovery), queries."""

import time

import pytest

from core.spatial.scene_graph import NodeStatus, SceneGraph


def test_ensure_room_idempotent():
    sg = SceneGraph()
    a = sg.ensure_room("Office")
    b = sg.ensure_room("Office")
    assert a.node_id == b.node_id and a.object_class == "room"
    assert len(sg.rooms()) == 1


def test_upsert_object_create_then_update():
    sg = SceneGraph()
    node, created = sg.upsert_object(persistent_id="OBJ_phone_1", object_class="phone",
                                     label="phone", position={"x": 0.5, "y": 0.5},
                                     room="office", confidence=0.9)
    assert created and node.room == "office" and node.parent is not None
    node2, created2 = sg.upsert_object(persistent_id="OBJ_phone_1", object_class="phone",
                                       label="phone", position={"x": 0.6, "y": 0.5},
                                       room="office", confidence=0.95)
    assert not created2 and node2.node_id == node.node_id
    assert node2.position["x"] == 0.6


def test_object_reparents_on_room_change():
    sg = SceneGraph()
    sg.upsert_object(persistent_id="OBJ_phone_1", object_class="phone", label="phone",
                     position={"x": 0.5, "y": 0.5}, room="office", confidence=0.9)
    sg.upsert_object(persistent_id="OBJ_phone_1", object_class="phone", label="phone",
                     position={"x": 0.5, "y": 0.5}, room="kitchen", confidence=0.9)
    assert sg.by_room("kitchen") and not sg.by_room("office")


def test_relationships_and_status():
    sg = SceneGraph()
    node, _ = sg.upsert_object(persistent_id="OBJ_laptop_1", object_class="laptop",
                               label="laptop", position={"x": 0.3, "y": 0.4},
                               room="office", confidence=0.9)
    rels = [{"relation": "on", "target": "X", "target_label": "desk"}]
    assert sg.set_relationships(node.node_id, rels) is True
    assert sg.set_relationships(node.node_id, rels) is False   # unchanged → no event
    sg.mark_status(node.node_id, NodeStatus.LOST)
    assert sg.by_persistent("OBJ_laptop_1").status == NodeStatus.LOST


def test_prune_removes_stale_lost_nodes():
    sg = SceneGraph()
    node, _ = sg.upsert_object(persistent_id="OBJ_cup_1", object_class="cup", label="cup",
                               position={"x": 0.1, "y": 0.1}, room="office", confidence=0.9)
    sg.mark_status(node.node_id, NodeStatus.REMOVED)
    node.last_seen = time.time() - 1000
    removed = sg.prune(forget_after_s=120)
    assert "OBJ_cup_1" in removed and sg.by_persistent("OBJ_cup_1") is None
    # rooms are never pruned
    assert sg.rooms()


def test_find_and_queries():
    sg = SceneGraph()
    sg.upsert_object(persistent_id="OBJ_phone_1", object_class="phone", label="my phone",
                     position={"x": 0.5, "y": 0.5}, room="office", confidence=0.9)
    assert sg.find("phone")[0].label == "my phone"
    assert sg.by_class("phone")
    assert sg.counts()["objects"] == 1
    snap = sg.snapshot()
    assert snap["node_count"] == 2 and len(snap["objects"]) == 1


def test_persistence_recovery(tmp_path):
    path = str(tmp_path / "spatial.db")
    sg = SceneGraph(path=path, persistent=True, session="S1")
    sg.upsert_object(persistent_id="OBJ_laptop_1", object_class="laptop", label="laptop",
                     position={"x": 0.3, "y": 0.4}, room="office", confidence=0.9)
    sg.save()
    sg.close()
    # reopen → load
    sg2 = SceneGraph(path=path, persistent=True, session="S1")
    n = sg2.load()
    assert n == 2                                       # room + object
    obj = sg2.by_persistent("OBJ_laptop_1")
    assert obj is not None and obj.room == "office"
    # children rebuilt
    room = sg2.by_persistent("room:office")
    assert obj.node_id in room.children
    sg2.close()
