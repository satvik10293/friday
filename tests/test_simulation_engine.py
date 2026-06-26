"""M11 — Cognitive simulation engine + director + service + controls/timeline."""

import pytest

from core.simulation.models import SimulationType
from core.simulation.service import SimulationService


@pytest.fixture
def sims(tmp_path):
    s = SimulationService(store_path=tmp_path / "sim.db")
    try:
        yield s
    finally:
        s.close()


def test_ten_simulation_types(sims):
    assert len(sims.types()) == 10
    assert "agent_society" in sims.types() and "business" in sims.types()


def test_agent_society_scale_simulation(sims):
    sim = sims.simulate("Will this architecture scale to 10,000 agents?",
                        params={"target_agents": 10000, "capacity": 5000})
    assert sim.sim_type == SimulationType.AGENT_SOCIETY.value
    assert sim.result is not None
    assert sim.result.recommendation.text
    assert sim.result.findings                 # discovered the failure/optimization
    assert len(sim.steps) > 1


def test_generic_simulation(sims):
    sim = sims.simulate("plan this project", params={"steps": 5})
    assert sim.result is not None
    assert sim.result.recommendation.confidence >= 0.0
    assert len(sim.steps) == 5


def test_create_then_run(sims):
    sim = sims.create("arch test", SimulationType.AGENT_SOCIETY,
                      params={"target_agents": 2000, "capacity": 5000})
    assert sim.result is None
    sims.run(sim)
    assert sim.result is not None and sim.result.ok       # 2000 < 5000 capacity → scales


def test_controls_playback(sims):
    sim = sims.simulate("scale test", params={"target_agents": 8000, "capacity": 4000})
    c = sims.controls(sim)
    assert c.total == len(sim.steps)
    c.fast_forward(3); assert c.position == 3
    c.replay(); assert c.position == 0
    c.pause(); assert c.paused
    c.goto(2); assert c.position == 2


def test_timeline_past_present_future(sims):
    sim = sims.simulate("scale test", params={"target_agents": 9000, "capacity": 5000})
    tl = sims.timeline(sim)
    view = tl.view(horizon=3)
    assert view["present"] is not None
    assert len(view["future"]) == 3            # predicted steps
    assert all(f["predicted"] for f in view["future"])


def test_fork(sims):
    sim = sims.simulate("scale", params={"target_agents": 6000, "capacity": 3000})
    fork = sims.fork(sim, at_step=2)
    assert fork.parent_id == sim.id
    assert len(fork.steps) == 2


def test_compare(sims):
    a = sims.simulate("scale A", params={"target_agents": 10000, "capacity": 4000})
    b = sims.simulate("scale B", params={"target_agents": 10000, "capacity": 9000})
    cmp = sims.compare(a, b)
    assert "metric_diff" in cmp and "failure_rate" in cmp["metric_diff"]
    assert cmp["a"]["id"] == a.id and cmp["b"]["id"] == b.id


def test_persistence_and_health(sims):
    sims.simulate("x", params={"steps": 3})
    assert sims.health()["persisted"] >= 1
    assert sims.list()
