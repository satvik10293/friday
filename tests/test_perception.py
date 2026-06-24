"""
tests/test_perception.py — FRIDAY 4.0 M6
Observation models + the Perception Manager: dedup/merge, significance, promotion,
archival, history, store persistence and restart recovery.
"""

import pytest

from core.perception import (
    Observation, ObservationBatch, ObservationConfidence, ObservationType,
    PerceptionEvent, PerceptionManager, PerceptionStore, WorldFeed, new_observation,
)
from core.world import WorldModel


def _obs(subject="test:a", payload=None, confidence=0.5, impact=0.5):
    return new_observation(ObservationType.CUSTOM, "unit", payload or {"v": 1},
                           confidence=confidence,
                           metadata={"subject": subject, "impact": impact})


# ── models ───────────────────────────────────────────────────────────────────
def test_new_observation_clamps_confidence():
    o = new_observation(ObservationType.SYSTEM, "s", {"x": 1}, confidence=5.0)
    assert o.confidence == 1.0 and len(o.id) == 12


def test_observation_roundtrip():
    o = _obs(payload={"a": 1, "b": 2})
    r = Observation.from_dict(o.to_dict())
    assert r.id == o.id and r.subject() == o.subject() and r.payload == {"a": 1, "b": 2}


def test_subject_and_value_signature():
    a = _obs(payload={"v": 1})
    b = _obs(payload={"v": 1})
    c = _obs(payload={"v": 2})
    assert a.subject() == b.subject() == "test:a"
    assert a.value_signature() == b.value_signature()
    assert a.value_signature() != c.value_signature()


def test_confidence_levels():
    assert ObservationConfidence.level(0.9) == "high"
    assert ObservationConfidence.level(0.6) == "medium"
    assert ObservationConfidence.level(0.3) == "low"
    assert ObservationConfidence.level(0.0) == "unknown"


def test_batch_helpers():
    batch = ObservationBatch(sensor="s")
    batch.add(new_observation(ObservationType.TIME, "t", {}))
    batch.add(new_observation(ObservationType.SYSTEM, "s", {}))
    assert len(batch) == 2
    assert len(batch.by_type(ObservationType.TIME)) == 1


def test_perception_event_values():
    assert PerceptionEvent.PROMOTED.value == "observation.promoted"


# ── manager ──────────────────────────────────────────────────────────────────
@pytest.fixture
def manager(tmp_path):
    store = PerceptionStore(path=tmp_path / "perc.db")
    pm = PerceptionManager(store=store)
    yield pm, store
    store.close()


def test_ingest_new_is_received(manager):
    pm, _ = manager
    r = pm.ingest(_obs())
    assert r["status"] == "received" and r["count"] == 1


def test_ingest_duplicate_is_ignored(manager):
    pm, _ = manager
    pm.ingest(_obs(payload={"v": 1}))
    r = pm.ingest(_obs(payload={"v": 1}))
    assert r["status"] == "ignored" and r["count"] == 2


def test_ingest_changed_value(manager):
    pm, _ = manager
    pm.ingest(_obs(payload={"v": 1}))
    r = pm.ingest(_obs(payload={"v": 2}))
    assert r["status"] == "changed"


def test_significance_higher_for_novel(manager):
    pm, _ = manager
    novel = pm.significance(_obs(confidence=0.9, impact=0.9), prev=None)
    routine = pm.significance(_obs(confidence=0.9, impact=0.9),
                              prev={"sig": _obs(confidence=0.9, impact=0.9).value_signature()})
    assert novel > routine


def test_low_value_duplicate_archived(manager):
    pm, store = manager
    pm.ingest(_obs(payload={"v": 1}, confidence=0.2, impact=0.0))
    r = pm.ingest(_obs(payload={"v": 1}, confidence=0.2, impact=0.0))
    assert r["archived"] is True
    assert store.get_observation(r["observation"].id)["status"] == "archived"


def test_history_tracked(manager):
    pm, _ = manager
    pm.ingest(_obs(payload={"v": 1}))
    pm.ingest(_obs(payload={"v": 2}))
    hist = pm.history("test:a")
    kinds = {h["kind"] for h in hist}
    assert "received" in kinds and "changed" in kinds


def test_promotion_to_world_model(tmp_path):
    store = PerceptionStore(path=tmp_path / "p.db")
    wm = WorldModel(path=tmp_path / "w.db")
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm))
    r = pm.ingest(_obs(subject="custom:hot", payload={"v": 1}, confidence=0.9, impact=0.9))
    assert r["promoted"] is True
    assert wm.counts()["entities"] == 1
    store.close(); wm.close()


def test_stats_shape(manager):
    pm, _ = manager
    pm.ingest(_obs())
    s = pm.stats()
    assert s["ingested"] == 1 and "store" in s


# ── persistence ──────────────────────────────────────────────────────────────
def test_observations_survive_restart(tmp_path):
    db = tmp_path / "persist.db"
    store1 = PerceptionStore(path=db)
    pm = PerceptionManager(store=store1)
    pm.ingest(_obs(subject="keep:me", payload={"v": 99}))
    store1.close()

    store2 = PerceptionStore(path=db)
    latest = store2.latest_for_subject("keep:me")
    assert latest is not None and latest["payload"] == {"v": 99}
    store2.close()


def test_store_counts_and_by_type(tmp_path):
    store = PerceptionStore(path=tmp_path / "p.db")
    pm = PerceptionManager(store=store)
    pm.ingest(new_observation(ObservationType.TIME, "time", {"hour": 9},
                              metadata={"subject": "time:clock"}))
    assert store.counts()["total"] == 1
    assert len(store.by_type(ObservationType.TIME)) == 1
    store.close()
