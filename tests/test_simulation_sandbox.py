"""M11 — Simulation sandbox isolation (Parts 9 & 13)."""

import pytest

from core.simulation.sandbox import SandboxViolation, SimulationSandbox
from core.simulation.models import (VirtualAgent, VirtualGoal, VirtualKnowledge,
                                     VirtualTask)


def test_sandbox_is_isolated_by_default():
    sb = SimulationSandbox("t")
    assert sb.is_sandboxed
    assert sb.assert_isolated() is True


def test_rejects_production_knowledge_service():
    sb = SimulationSandbox("t")

    class FakeKnowledgeService:
        def remember_knowledge(self, *a, **k): ...
        store = object()
    with pytest.raises(SandboxViolation):
        sb.add_agent(FakeKnowledgeService())   # production-like → rejected


def test_rejects_objects_with_db_conn():
    sb = SimulationSandbox("t")

    class FakeStore:
        def conn(self): ...
        def execute(self, *a): ...
    with pytest.raises(SandboxViolation):
        sb.add_agent(FakeStore())


def test_every_gate_runs_the_production_guard():
    """add_goal/add_knowledge/add_task must guard like add_agent does — a
    VirtualGoal SUBCLASS smuggling a production reference passes isinstance
    but must still be rejected."""
    sb = SimulationSandbox("t")

    class SmuggledGoal(VirtualGoal):
        store = object()               # production marker on a virtual type

    class SmuggledKnowledge(VirtualKnowledge):
        def execute(self, *a): ...

    class SmuggledTask(VirtualTask):
        memory_service = object()

    with pytest.raises(SandboxViolation):
        sb.add_goal(SmuggledGoal(name="g"))
    with pytest.raises(SandboxViolation):
        sb.add_knowledge(SmuggledKnowledge(title="k"))
    with pytest.raises(SandboxViolation):
        sb.add_task(SmuggledTask(name="t"))


def test_assert_isolated_inspects_container_contents():
    """The container dicts are primitives — isolation must check what's
    INSIDE them, not just the attributes themselves."""
    sb = SimulationSandbox("t")
    agent = VirtualAgent(name="a")
    sb.add_agent(agent)
    agent.store = object()             # contaminated after admission
    with pytest.raises(SandboxViolation):
        sb.assert_isolated()


def test_only_virtual_types_admitted():
    sb = SimulationSandbox("t")
    with pytest.raises(SandboxViolation):
        sb.add_agent({"not": "a VirtualAgent"})
    sb.add_agent(VirtualAgent(name="a"))       # the real virtual type is fine
    assert sb.counts()["agents"] == 1


def test_virtual_entities_admitted():
    sb = SimulationSandbox("t")
    sb.add_agent(VirtualAgent(name="w"))
    sb.add_goal(VirtualGoal(name="g"))
    sb.add_knowledge(VirtualKnowledge(title="k"))
    sb.add_task(VirtualTask(name="t"))
    c = sb.counts()
    assert c == {"agents": 1, "goals": 1, "knowledge": 1, "tasks": 1}


def test_real_services_unaffected_by_simulation(tmp_path):
    """A simulation must never mutate production knowledge/goals."""
    from core.knowledge.knowledge_store import KnowledgeStore
    from core.knowledge.knowledge_index import KnowledgeIndex
    from core.knowledge.knowledge_service import KnowledgeService
    from core.knowledge.vault import ObsidianVault
    from core.simulation.service import SimulationService

    ks = KnowledgeService(store=KnowledgeStore(path=tmp_path / "k.db"),
                          index=KnowledgeIndex(), vault=ObsidianVault(root=tmp_path / "v"))
    ks.teach("Real", "production knowledge")
    before = ks.stats()["total"]

    sims = SimulationService(store_path=tmp_path / "sim.db")
    sims.simulate("scale to 10000 agents", params={"target_agents": 10000, "capacity": 4000})
    sims.simulate("plan a project", params={"steps": 5})

    assert ks.stats()["total"] == before       # production knowledge untouched
    sims.close(); ks.store.close()


def test_spawn_agents_bulk():
    sb = SimulationSandbox("t")
    sb.spawn_agents(100)
    assert sb.counts()["agents"] == 100
    assert sb.snapshot()["healthy_agents"] == 100
