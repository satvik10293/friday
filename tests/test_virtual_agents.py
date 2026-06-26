"""M11 — Virtual agents / goals / knowledge live only inside the sandbox."""

from core.simulation.models import (VirtualAgent, VirtualGoal, VirtualKnowledge,
                                     VirtualTask)
from core.simulation.sandbox import SimulationSandbox
from core.simulation.engine import SimulationEngine
from core.simulation.models import Scenario, Simulation, SimulationType


def test_virtual_agent_defaults():
    a = VirtualAgent(name="w")
    assert a.healthy and a.role == "worker" and a.id


def test_engine_populates_virtual_world():
    sb = SimulationSandbox("world")
    sim = Simulation(sim_type=SimulationType.AGENT_SOCIETY.value,
                     scenario=Scenario(sim_type=SimulationType.AGENT_SOCIETY.value,
                                       params={"target_agents": 500, "capacity": 200}))
    SimulationEngine().run(sim, sandbox=sb)
    assert sb.counts()["agents"] > 0           # virtual agents materialised (sampled)


def test_failures_marked_in_virtual_world():
    sb = SimulationSandbox("world")
    sim = Simulation(sim_type=SimulationType.AGENT_SOCIETY.value,
                     scenario=Scenario(sim_type=SimulationType.AGENT_SOCIETY.value,
                                       params={"target_agents": 10000, "capacity": 2000,
                                               "optimize": False}))
    SimulationEngine().run(sim, sandbox=sb)
    snap = sb.snapshot()
    assert snap["agents"] > 0
    assert snap["healthy_agents"] < snap["agents"]   # some virtual agents failed


def test_generic_sim_creates_virtual_goals_and_tasks():
    sb = SimulationSandbox("world")
    sim = Simulation(sim_type=SimulationType.PROJECT_PLANNING.value,
                     scenario=Scenario(sim_type=SimulationType.PROJECT_PLANNING.value,
                                       params={"steps": 4}))
    SimulationEngine().run(sim, sandbox=sb)
    assert sb.counts()["goals"] >= 1
    assert sb.counts()["tasks"] == 4


def test_virtual_world_independent_per_simulation():
    e = SimulationEngine()
    sb1, sb2 = SimulationSandbox("a"), SimulationSandbox("b")
    for sb, n in ((sb1, 300), (sb2, 100)):
        sim = Simulation(sim_type=SimulationType.AGENT_SOCIETY.value,
                         scenario=Scenario(sim_type=SimulationType.AGENT_SOCIETY.value,
                                           params={"target_agents": n, "capacity": 1000}))
        e.run(sim, sandbox=sb)
    assert sb1.counts()["agents"] != sb2.counts()["agents"]   # isolated worlds


def test_virtual_entities_never_leak_to_production():
    # virtual entities are plain dataclasses with no store/conn — they cannot reach
    # production by construction
    for obj in (VirtualAgent(), VirtualGoal(), VirtualKnowledge(), VirtualTask()):
        assert not hasattr(obj, "store")
        assert not hasattr(obj, "conn")
