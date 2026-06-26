"""M11 — Agent society: leader/worker hierarchy + lifecycle + communication."""

import pytest

from core.society.bus import AgentBus, DirectMessageError
from core.society.leaders import LEADER_REGISTRY, LeaderRole, select_leader
from core.society.models import Task
from core.society.society import AgentSociety
from core.society.store import SocietyStore
from core.society.workers import WORKER_TEMPLATES


@pytest.fixture
def society(tmp_path):
    s = AgentSociety(store=SocietyStore(path=tmp_path / "society.db"), use_processes=False)
    try:
        yield s
    finally:
        s.close()


def test_eight_permanent_leaders():
    assert len(LEADER_REGISTRY) == 8
    assert {r.value for r in LeaderRole} == set(LEADER_REGISTRY.keys())


def test_worker_catalogue():
    assert "Python Debugger" in WORKER_TEMPLATES
    assert "Math Solver" in WORKER_TEMPLATES


def test_full_lifecycle_spawn_and_destroy(society):
    res = society.solve("debug this", domain="coding",
                        payload={"code": "x == None", "architecture": {"components": [1], "auth": False}})
    assert res.ok
    assert res.workers_spawned == 2          # debugger + architecture reviewer
    assert res.workers_destroyed == res.workers_spawned
    assert len(society.coordinator.active_workers()) == 0   # all destroyed


def test_leader_selection_by_domain(society):
    leader = select_leader(Task(description="anything", domain="planning"))
    assert leader.role == LeaderRole.PLANNING


def test_leader_selection_by_keyword():
    assert select_leader(Task(description="please debug my code")).role == LeaderRole.CODING
    assert select_leader(Task(description="research this paper")).role == LeaderRole.RESEARCH
    assert select_leader(Task(description="will it scale under stress")).role == LeaderRole.SIMULATION


def test_merged_results(society):
    res = society.solve("solve math", domain="planning", payload={"expression": "2 + 3 * 4"})
    assert res.ok
    assert res.merged["Math Solver"]["value"] == 14


def test_workers_cannot_spawn_workers():
    # workers are plain functions in worker_tasks — structurally they import nothing
    # that could create agents, so they cannot spawn workers.
    import types
    import core.society.worker_tasks as wt
    imported = {v.__name__ for v in vars(wt).values() if isinstance(v, types.ModuleType)}
    forbidden = {"core.society.coordinator", "core.society.scheduler",
                 "core.society.society", "core.agent_runtime"}
    assert not (imported & forbidden)
    assert not hasattr(wt, "PassiveBrainCoordinator")
    assert not hasattr(wt, "spawn_worker")


def test_only_leaders_create_workers(society):
    # the coordinator spawns workers only from a leader's decomposition
    before = society.store.counts()["agents_ever"]
    society.solve("doc it", domain="knowledge", payload={"topic": "X", "points": ["a"]})
    after = society.store.counts()["agents_ever"]
    assert after > before


def test_communication_routes_through_passive_brain(society):
    society.solve("debug", domain="coding", payload={"code": "y == None"})
    history = society.coordinator.bus.history()
    assert history
    # every relayed message hops through the passive brain
    assert all(m["relay"] == "passive_brain" for m in history if m["kind"] != "direct")


def test_direct_agent_messaging_forbidden():
    bus = AgentBus()
    with pytest.raises(DirectMessageError):
        bus.deliver_direct("worker-1", "worker-2", {"x": 1})
    # but relaying through the coordinator is fine
    assert bus.deliver_direct("worker-1", "passive_brain", {"x": 1})


def test_status_and_health(society):
    society.solve("debug", domain="coding", payload={"code": "z == None"})
    st = society.status()
    assert st["hierarchy"] == ["executive", "passive_brain", "leaders", "workers"]
    assert len(st["leaders"]) == 8
    assert society.health()["status"] == "ok"
