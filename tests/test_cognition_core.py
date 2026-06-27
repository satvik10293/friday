"""M13 — Cognition Core integration: service, world feed, events, dashboard, benchmark."""

import json

import pytest

from core.cognition_core.benchmark import run_benchmark
from core.cognition_core.repositories import (InMemoryBeliefRepository,
                                              InMemoryEntityRepository)
from core.cognition_core.service import CognitionCore, get_cognition_core


@pytest.fixture
def core():
    c = CognitionCore(entity_repository=InMemoryEntityRepository(),
                      belief_repository=InMemoryBeliefRepository())
    try:
        yield c
    finally:
        c.close()


# ── resolution + beliefs through the facade ────────────────────────────────────────
def test_resolve_and_believe(core):
    sid = core.resolve("application", "Chrome").stable_id
    core.assert_belief(sid, "is_open", True, confidence=0.8)
    assert core.beliefs_about(sid)[0].value is True


def test_merge_repoints_beliefs(core):
    a = core.resolve("person", "Sat").stable_id
    b = core.resolve("person", "Satvik Rao").stable_id
    core.assert_belief(b, "role", "owner", confidence=0.8)
    core.merge(a, b)
    assert any(x.value == "owner" for x in core.beliefs_about(a))
    assert core.get_entity(b) is None


# ── observation pipeline integration (never bypasses resolution) ───────────────────
def test_resolving_world_feed(core):
    from core.perception.models import new_observation, ObservationType
    from core.world.world_model import WorldModel
    import tempfile, os
    wm = WorldModel(path=os.path.join(tempfile.mkdtemp(), "world.db"))
    feed = core.resolving_world_feed(wm)

    obs = new_observation(ObservationType.APPLICATION, "screen",
                          payload={"name": "Chrome"}, confidence=0.9,
                          metadata={"entity_kind": "application", "entity_name": "Chrome"})
    entity = feed.observe(obs)
    # the world entity now carries a stable id minted by the resolver
    assert entity.attributes.get("stable_id", "").startswith("ENT_")
    assert core.entities_by_kind("application")        # resolver created the entity
    wm.close()


def test_entity_linker(core):
    sid = core.linker().link("device", "Webcam")
    assert sid.startswith("ENT_") and core.get_entity(sid).primary_label == "Webcam"


# ── events on the runtime bus ──────────────────────────────────────────────────────
def test_emits_events(runtime, tmp_path):
    import time as _t
    from core.cognition_core.events import CognitionEvent
    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(CognitionEvent.ENTITY_CREATED, _handler)
    c = CognitionCore(entity_repository=InMemoryEntityRepository(),
                      belief_repository=InMemoryBeliefRepository(), runtime=runtime)
    c.resolve("application", "Chrome")
    deadline = _t.time() + 2.0
    while not seen and _t.time() < deadline:
        _t.sleep(0.02)
    assert seen, "expected an entity.created runtime event"
    c.close()


# ── observability ──────────────────────────────────────────────────────────────────
def test_dashboard(core):
    core.resolve("application", "Chrome")
    core.assert_belief("ENT_000001", "is_open", True, confidence=0.7)
    d = core.dashboard()
    assert d["title"] == "Cognition" and d["entities"] >= 1 and d["beliefs"] >= 1
    assert "by_kind" in d and "self_model" in d and "metrics" in d


def test_manifest(core):
    m = core.manifest()
    assert m["subsystem"] == "cognition_core" and m["milestone"] == "M13"
    for section in ("inputs", "outputs", "dependencies", "events", "metrics",
                    "configuration", "public_api", "invariants"):
        assert section in m


def test_health(core):
    assert core.health()["status"] == "ok"


def test_singleton():
    assert get_cognition_core() is get_cognition_core()


def test_side_effect_free_import():
    import importlib
    importlib.import_module("core.cognition_core")
    importlib.import_module("core.cognition_core.service")


# ── benchmark (charter: measure resolution accuracy + duplicate rate) ──────────────
def test_benchmark_meets_targets():
    rep = run_benchmark(repeats=15)
    assert rep.resolution_accuracy >= 0.95          # string variants resolve correctly
    assert rep.duplicate_rate <= 0.05               # almost no duplicate entities
    assert rep.throughput_per_s > 1000              # fast resolution
    assert rep.avg_belief_update_ms < 50            # fast belief updates


def test_benchmark_serializable():
    json.dumps(run_benchmark(repeats=5).to_dict())
