"""
tests/test_observation_world.py — FRIDAY 4.0 M6
World Model feed + promotion rules: observations becoming world entities by high
confidence, repeated occurrence, or goal relevance.
"""

import pytest

from core.perception import (
    ObservationType, PerceptionManager, PerceptionStore, WorldFeed, new_observation,
)
from core.world import WorldModel


@pytest.fixture
def env(tmp_path):
    store = PerceptionStore(path=tmp_path / "p.db")
    wm = WorldModel(path=tmp_path / "w.db")
    yield store, wm
    store.close(); wm.close()


def _obs(subject, payload=None, confidence=0.5, impact=0.5):
    return new_observation(ObservationType.CUSTOM, "unit", payload or {"v": 1},
                           confidence=confidence,
                           metadata={"subject": subject, "impact": impact})


# ── WorldFeed adapter ────────────────────────────────────────────────────────
def test_world_feed_creates_entity(env):
    _, wm = env
    feed = WorldFeed(wm)
    obs = new_observation(ObservationType.SYSTEM, "system", {"cpu_pct": 50},
                          confidence=0.9, metadata={"subject": "system:host"})
    entity = feed.observe(obs)
    assert entity is not None and entity.kind == "system"
    assert wm.get_entity("system:system").state["cpu_pct"] == 50


def test_world_feed_uses_entity_metadata(env):
    _, wm = env
    feed = WorldFeed(wm)
    obs = new_observation(ObservationType.APPLICATION, "fusion", {"name": "Chrome"},
                          confidence=0.9,
                          metadata={"entity_kind": "application", "entity_name": "Chrome"})
    feed.observe(obs)
    assert wm.get_entity("application:Chrome") is not None


def test_world_feed_merges_state(env):
    _, wm = env
    feed = WorldFeed(wm)
    feed.observe(_obs("system:host", {"cpu_pct": 10}, confidence=0.9))
    feed.observe(_obs("system:host", {"ram_pct": 40}, confidence=0.9))
    # both readings accumulate on the same entity
    ent = wm.get_entity("custom:unit")
    assert "cpu_pct" in ent.state and "ram_pct" in ent.state


# ── promotion rules ──────────────────────────────────────────────────────────
def test_high_confidence_high_significance_promotes(env):
    store, wm = env
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm))
    r = pm.ingest(_obs("custom:hot", confidence=0.9, impact=0.9))
    assert r["promoted"] is True
    assert wm.counts()["entities"] == 1


def test_repeated_occurrence_promotes(env):
    store, wm = env
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm))
    # conf high enough, but low significance — only repetition should trigger promotion
    r1 = pm.ingest(_obs("custom:rep", payload={"v": 1}, confidence=0.7, impact=0.1))
    r2 = pm.ingest(_obs("custom:rep", payload={"v": 1}, confidence=0.7, impact=0.1))
    assert r1["promoted"] is False and r2["promoted"] is False
    r3 = pm.ingest(_obs("custom:rep", payload={"v": 1}, confidence=0.7, impact=0.1))
    assert r3["promoted"] is True            # count >= 3


def test_low_confidence_never_promotes(env):
    store, wm = env
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm))
    for _ in range(4):
        r = pm.ingest(_obs("custom:weak", payload={"v": 1}, confidence=0.4, impact=0.9))
    assert r["promoted"] is False
    assert wm.counts()["entities"] == 0


def test_goal_relevance_promotes(env, goal_service):
    store, wm = env
    g = goal_service.create_goal("Inspect chrome browser logs")
    goal_service.activate_goal(g.goal_id)
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm), goal_service=goal_service)
    # high confidence + goal-relevant text (chrome) → promotes despite low significance
    r = pm.ingest(new_observation(
        ObservationType.APPLICATION, "process", {"process": "chrome.exe"},
        confidence=0.75, metadata={"subject": "process:chrome", "impact": 0.1}))
    assert r["promoted"] is True


def test_promoted_query(env):
    store, wm = env
    pm = PerceptionManager(store=store, world_feed=WorldFeed(wm))
    pm.ingest(_obs("custom:hot", confidence=0.9, impact=0.9))
    assert len(pm.promoted()) == 1


def test_world_feed_batch(env):
    _, wm = env
    feed = WorldFeed(wm)
    n = feed.feed([
        new_observation(ObservationType.SYSTEM, "system", {"cpu_pct": 5}, confidence=0.9,
                        metadata={"subject": "system:host"}),
        new_observation(ObservationType.TIME, "time", {"hour": 9}, confidence=1.0,
                        metadata={"subject": "time:clock"}),
    ])
    assert n == 2 and wm.counts()["entities"] == 2 and feed.promoted == 2
