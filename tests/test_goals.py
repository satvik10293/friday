"""
tests/test_goals.py — FRIDAY 4.0 M4
Goal model, store persistence, lifecycle, progress roll-up, observability,
memory integration, and recovery-after-restart.
"""

import pytest

from core.goals import (
    Goal, GoalStatus, GoalService, GoalStore, new_goal, validate_goal,
)
from core.observability import DecisionLog


@pytest.fixture
def store(tmp_path):
    s = GoalStore(path=tmp_path / "goals.db")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def service(store, memory_service, tmp_path):
    dec = DecisionLog(tmp_path / "dec_goals.db")
    return GoalService(store=store, memory_service=memory_service, decision_log=dec)


# ── model ────────────────────────────────────────────────────────────────────
def test_new_goal_defaults_and_clamp():
    g = new_goal("Test", confidence=5.0)
    assert g.status == GoalStatus.PENDING
    assert g.confidence == 1.0           # clamped to [0, 1]
    assert len(g.goal_id) == 12
    assert g.created_at > 0 and g.updated_at == g.created_at


def test_validate_goal_rejects_empty_title():
    g = new_goal("ok")
    g.title = "   "
    with pytest.raises(ValueError):
        validate_goal(g)


def test_goal_row_roundtrip():
    g = new_goal("Roundtrip", description="d", dependencies=["a", "b"],
                 metadata={"k": "v"})
    g.status = GoalStatus.ACTIVE
    restored = Goal.from_row(_as_row(g))
    assert restored.goal_id == g.goal_id
    assert restored.status == GoalStatus.ACTIVE
    assert restored.dependencies == ["a", "b"]
    assert restored.metadata == {"k": "v"}


# ── store ────────────────────────────────────────────────────────────────────
def test_store_crud(store):
    g = new_goal("Persisted")
    store.create_goal(g)
    got = store.get_goal(g.goal_id)
    assert got is not None and got.title == "Persisted"

    got.status = GoalStatus.ACTIVE
    store.update_goal(got)
    assert store.get_goal(g.goal_id).status == GoalStatus.ACTIVE

    store.delete_goal(g.goal_id)
    assert store.get_goal(g.goal_id) is None


def test_store_list_filters(store):
    a = new_goal("A", owner="satvik")
    b = new_goal("B", owner="other")
    b.status = GoalStatus.ACTIVE
    store.create_goal(a)
    store.create_goal(b)
    assert {g.title for g in store.list_goals(owner="satvik")} == {"A"}
    assert {g.title for g in store.list_goals(status=GoalStatus.ACTIVE)} == {"B"}


def test_counts_by_status(store):
    store.create_goal(new_goal("p1"))
    store.create_goal(new_goal("p2"))
    done = new_goal("d")
    done.status = GoalStatus.COMPLETED
    store.create_goal(done)
    c = store.counts_by_status()
    assert c["pending"] == 2 and c["completed"] == 1 and c["total"] == 3


def test_events_history(store):
    g = new_goal("Tracked")
    store.create_goal(g)
    store.add_event(g.goal_id, "created", "born", {"x": 1})
    store.add_event(g.goal_id, "activated", "")
    events = store.get_events(g.goal_id)
    assert [e["kind"] for e in events] == ["created", "activated"]
    assert events[0]["data"] == {"x": 1}


# ── service lifecycle ────────────────────────────────────────────────────────
def test_service_create_and_transitions(service):
    g = service.create_goal("Ship feature", priority=1)
    assert g.status == GoalStatus.PENDING

    service.activate_goal(g.goal_id)
    assert service.get_goal(g.goal_id).status == GoalStatus.ACTIVE

    service.complete_goal(g.goal_id, "done")
    done = service.get_goal(g.goal_id)
    assert done.status == GoalStatus.COMPLETED
    assert done.completion_percent == 100.0


def test_service_fail_records_reason(service):
    g = service.create_goal("Risky")
    service.fail_goal(g.goal_id, "credentials missing")
    failed = service.get_goal(g.goal_id)
    assert failed.status == GoalStatus.FAILED
    assert failed.metadata["failure_reason"] == "credentials missing"


def test_progress_rolls_up_to_parent(service):
    root = service.plan("build a weather dashboard")
    children = service.list_goals()
    kids = [g for g in children if g.parent_goal == root.goal_id]
    assert len(kids) == 6

    # complete half the children
    for g in kids[:3]:
        service.complete_goal(g.goal_id)
    parent = service.get_goal(root.goal_id)
    assert 0 < parent.completion_percent < 100

    for g in kids[3:]:
        service.complete_goal(g.goal_id)
    parent = service.get_goal(root.goal_id)
    assert parent.status == GoalStatus.COMPLETED
    assert parent.completion_percent == 100.0


# ── observability / memory integration ───────────────────────────────────────
def test_completion_writes_memory(service, memory_service):
    g = service.create_goal("Learn FAISS")
    service.complete_goal(g.goal_id, "indexed the vault")
    hits = memory_service.recall("Learn FAISS")
    assert any("Learn FAISS" in h["content"] for h in hits)


def test_decision_log_records_actions(service, tmp_path):
    g = service.create_goal("Audited goal")
    service.complete_goal(g.goal_id)
    rows = service._decision.recent(limit=10)
    intents = {r["intent"] for r in rows}
    assert "goal.create" in intents and "goal.complete" in intents


def test_runtime_event_emitted(service, runtime):
    import time as _t
    from core.goals import GoalEvent

    seen = []

    async def _handler(ev):
        seen.append(ev)

    runtime.on(GoalEvent.COMPLETED, _handler)
    service.attach(runtime)
    g = service.create_goal("Emit me")
    service.complete_goal(g.goal_id)

    # event delivery is async; drain via a short wait
    deadline = _t.time() + 2.0
    while not seen and _t.time() < deadline:
        _t.sleep(0.02)
    assert seen, "expected a goal.completed runtime event"


# ── recovery ─────────────────────────────────────────────────────────────────
def test_goals_survive_restart(tmp_path, memory_service):
    db = tmp_path / "persist.db"
    s1 = GoalStore(path=db)
    svc1 = GoalService(store=s1, memory_service=memory_service)
    root = svc1.plan("build a chat app")
    gid = root.goal_id
    s1.close()

    # fresh store + service over the same DB file
    s2 = GoalStore(path=db)
    svc2 = GoalService(store=s2, memory_service=memory_service)
    recovered = svc2.get_goal(gid)
    assert recovered is not None and recovered.title == "build a chat app"
    assert len(svc2.list_goals()) >= 7   # root + 6 phases
    s2.close()


def _as_row(g: Goal) -> dict:
    cols = ["goal_id", "title", "description", "status", "priority", "created_at",
            "updated_at", "parent_goal", "dependencies", "owner", "confidence",
            "completion_percent", "metadata"]
    return dict(zip(cols, g.to_row()))
