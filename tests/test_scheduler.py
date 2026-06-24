"""
tests/test_scheduler.py — FRIDAY 4.0 M4
Scheduler activation, dependency gating, blocked-on-failure detection, and
next-actions ordering.
"""

import pytest

from core.goals import GoalScheduler, GoalStore, GoalStatus, new_goal


@pytest.fixture
def store(tmp_path):
    s = GoalStore(path=tmp_path / "sched.db")
    try:
        yield s
    finally:
        s.close()


def _chain(store, n=3):
    """Create a linear dependency chain g0 <- g1 <- g2 ... all PENDING."""
    goals = []
    prev = None
    for i in range(n):
        g = new_goal(f"step-{i}", priority=i + 1,
                     dependencies=[prev.goal_id] if prev else [])
        store.create_goal(g)
        goals.append(g)
        prev = g
    return goals


def test_tick_activates_only_dependency_free_goal(store):
    g0, g1, g2 = _chain(store)
    result = GoalScheduler(store).tick()
    assert result["activated"] == [g0.goal_id]      # only the head is ready
    assert store.get_goal(g0.goal_id).status == GoalStatus.ACTIVE
    assert store.get_goal(g1.goal_id).status == GoalStatus.PENDING


def test_completing_dependency_unlocks_next(store):
    g0, g1, g2 = _chain(store)
    sched = GoalScheduler(store)
    sched.tick()

    # complete the head; next tick should activate g1
    g0 = store.get_goal(g0.goal_id)
    g0.status = GoalStatus.COMPLETED
    store.update_goal(g0)
    result = sched.tick()
    assert result["activated"] == [g1.goal_id]
    assert store.get_goal(g2.goal_id).status == GoalStatus.PENDING


def test_failed_dependency_blocks_dependent(store):
    g0, g1, g2 = _chain(store)
    g0 = store.get_goal(g0.goal_id)
    g0.status = GoalStatus.FAILED
    store.update_goal(g0)

    result = GoalScheduler(store).tick()
    assert g1.goal_id in result["blocked"]
    assert store.get_goal(g1.goal_id).status == GoalStatus.BLOCKED


def test_next_actions_priority_order(store):
    high = new_goal("urgent", priority=1)
    low = new_goal("later", priority=9)
    for g in (low, high):
        g.status = GoalStatus.ACTIVE
        store.create_goal(g)
    actions = GoalScheduler(store).next_actions()
    assert [g.title for g in actions] == ["urgent", "later"]


def test_ready_goals_excludes_active_and_blocked(store):
    g0, g1, _ = _chain(store)
    ready = GoalScheduler(store).ready_goals()
    # only the dependency-free head is ready
    assert [g.goal_id for g in ready] == [g0.goal_id]


def test_tick_summary_shape(store):
    _chain(store, 2)
    result = GoalScheduler(store).tick()
    assert set(result) == {"activated", "blocked", "active", "checked", "ts"}
    assert result["checked"] == 2
