"""M11 — Interactive cognitive space: universe build, search, visual language, resilience."""

import pytest

from core.cognitive_space.service import CognitiveSpace
from core.cognitive_space.models import VISUAL_LANGUAGE, ZoomLevel


@pytest.fixture
def space(tmp_path, knowledge_service, goal_service):
    from core.society.society import AgentSociety
    from core.society.store import SocietyStore
    from core.simulation.service import SimulationService
    knowledge_service.teach("Python", "lang", category="Python")
    knowledge_service.teach("Flask", "web", category="Flask")
    g = goal_service.create_goal("Ship", priority=1); goal_service.activate_goal(g.goal_id)
    soc = AgentSociety(store=SocietyStore(path=tmp_path / "s.db"), use_processes=False)
    soc.solve("debug", domain="coding", payload={"code": "x==None"})
    sims = SimulationService(store_path=tmp_path / "sim.db")
    sim = sims.simulate("scale to 5000 agents", params={"target_agents": 5000, "capacity": 3000})
    cs = CognitiveSpace(knowledge_service=knowledge_service, goal_service=goal_service,
                        society=soc, simulation_service=sims)
    cs._focus_sim = sim.id
    try:
        yield cs
    finally:
        soc.close(); sims.close()


def test_universe_level(space):
    u = space.universe()
    assert u["level"] == 1 and u["level_name"] == "UNIVERSE"
    kinds = {n["kind"] for n in u["nodes"]}
    assert {"goal", "knowledge", "agent", "simulation"} <= kinds


def test_all_six_levels_build(space):
    for lvl in range(1, 7):
        b = space.build(lvl, focus=getattr(space, "_focus_sim", None) if lvl == 6 else None)
        assert b["counts"]["nodes"] >= 0
        assert "nodes" in b and "edges" in b


def test_nodes_have_visual_language(space):
    u = space.universe()
    for n in u["nodes"]:
        assert "visual" in n and "color" in n


def test_visual_language_mapping():
    assert VISUAL_LANGUAGE["knowledge"]["visual"] == "star"
    assert VISUAL_LANGUAGE["goal"]["visual"] == "attractor"
    assert VISUAL_LANGUAGE["agent"]["visual"] == "entity"
    assert VISUAL_LANGUAGE["task"]["visual"] == "energy"
    assert VISUAL_LANGUAGE["decision"]["visual"] == "convergence"
    assert VISUAL_LANGUAGE["simulation"]["visual"] == "universe"


def test_global_search_focuses(space):
    r = space.search("flask")
    assert r["count"] >= 1
    hit = r["results"][0]
    assert "focus" in hit and "level" in hit["focus"] and "node_id" in hit["focus"]


def test_search_across_domains(space):
    assert space.search("python")["count"] >= 1     # knowledge
    assert space.search("ship")["count"] >= 1       # goal
    assert space.search("debug")["count"] >= 1      # agent/worker


def test_thought_chain_from_simulation(space):
    b = space.build(ZoomLevel.THOUGHT_CHAIN.value, focus=space._focus_sim)
    assert b["counts"]["nodes"] > 0
    assert b["counts"]["edges"] == b["counts"]["nodes"] - 1   # a linear chain


def test_resilient_to_missing_services():
    cs = CognitiveSpace()      # no services at all
    u = cs.universe()
    assert u["counts"]["nodes"] >= 1           # still renders (the FRIDAY core)
    assert cs.search("anything")["count"] == 0
    assert cs.health()["status"] == "ok"


def test_partition_present(space):
    u = space.universe()
    assert "partition" in u and isinstance(u["partition"], dict)
