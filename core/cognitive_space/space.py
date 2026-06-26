"""
core/cognitive_space/space.py — FRIDAY 4.0 (M11)
Builds the cognitive universe at any of the six zoom levels from FRIDAY's live
subsystems. Each builder is resilient (a missing/failing service yields fewer nodes,
never a crash) and LOD-bounded (capped to the level's node budget, laid out
deterministically, partitioned for culling).
"""

from __future__ import annotations

from typing import Optional

from core.mission_control.resilience import safe_call
from .models import SpaceEdge, SpaceNode, ZoomLevel
from .zoom import apply_budget, budget_for, partition, place


class CognitiveSpaceBuilder:
    def __init__(self, *, knowledge_service=None, goal_service=None, society=None,
                 simulation_service=None, user_model=None) -> None:
        self.knowledge = knowledge_service
        self.goals = goal_service
        self.society = society
        self.simulations = simulation_service
        self.user_model = user_model

    # ── public ──────────────────────────────────────────────────────────────────
    def build(self, level: int = 1, focus: Optional[str] = None) -> dict:
        level = int(level)
        builders = {
            ZoomLevel.UNIVERSE.value: self._universe,
            ZoomLevel.DOMAIN.value: self._domain,
            ZoomLevel.TEAM.value: self._team,
            ZoomLevel.AGENT.value: self._agent,
            ZoomLevel.TASK.value: self._task,
            ZoomLevel.THOUGHT_CHAIN.value: lambda: self._thought_chain(focus),
        }
        nodes, edges = safe_call("space", builders.get(level, self._universe),
                                 default=([], []))
        nodes = apply_budget(nodes, level)
        for i, n in enumerate(nodes):
            if n.position == (0.0, 0.0, 0.0):
                n.position = place(i, len(nodes))
        node_ids = {n.id for n in nodes}
        edges = [e for e in edges if e.source in node_ids and e.target in node_ids]
        return {
            "level": level, "level_name": ZoomLevel(level).name if level in
            [z.value for z in ZoomLevel] else "UNIVERSE",
            "budget": budget_for(level), "focus": focus,
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
            "partition": {str(k): v for k, v in partition(nodes).items()},
            "counts": {"nodes": len(nodes), "edges": len(edges)},
        }

    # ── Level 1: Universe ───────────────────────────────────────────────────────
    def _universe(self):
        core = SpaceNode("friday-core", "decision", "FRIDAY", level=1, size=18)
        nodes, edges = [core], []
        summaries = [
            ("goals", "goal", self._count(lambda: len(self.goals.list_goals()))),
            ("knowledge", "knowledge", self._count(lambda: self.knowledge.stats().get("total", 0))),
            ("projects", "project", self._count(lambda: len(self.user_model.projects.active()))),
            ("agents", "agent", self._count(lambda: len(self.society.leaders))),
            ("models", "model", self._count(self._model_count)),
            ("simulations", "simulation", self._count(lambda: len(self.simulations.list()))),
        ]
        for name, kind, count in summaries:
            nid = f"universe:{name}"
            nodes.append(SpaceNode(nid, kind, f"{name.capitalize()} ({count})",
                                   level=1, group=name, size=8 + min(20, count),
                                   meta={"count": count}))
            edges.append(SpaceEdge("friday-core", nid, "contains"))
        return nodes, edges

    # ── Level 2: Domain ─────────────────────────────────────────────────────────
    def _domain(self):
        nodes, edges = [], []
        cats = safe_call("kcats", lambda: self.knowledge.stats().get("by_category", {}),
                         default={})
        for cat, n in (cats or {}).items():
            nid = f"domain:know:{cat}"
            nodes.append(SpaceNode(nid, "knowledge", f"{cat} ({n})", level=2,
                                   group="knowledge", size=6 + min(16, n)))
        for role in safe_call("leaders", lambda: list(self.society.leaders.keys()), default=[]):
            nodes.append(SpaceNode(f"domain:team:{role}", "agent", f"{role} team",
                                   level=2, group="agents", size=10))
        # goal clusters by status
        clusters: dict = {}
        for g in safe_call("goals", lambda: self.goals.list_goals(), default=[]):
            st = g.status.value if hasattr(g.status, "value") else str(g.status)
            clusters[st] = clusters.get(st, 0) + 1
        for st, n in clusters.items():
            nodes.append(SpaceNode(f"domain:goals:{st}", "goal", f"{st} goals ({n})",
                                   level=2, group="goals", size=8 + min(14, n)))
        return nodes, edges

    # ── Level 3: Team ───────────────────────────────────────────────────────────
    def _team(self):
        from core.society.workers import templates_for
        nodes, edges = [], []
        for role, leader in safe_call("leaders", lambda: self.society.leaders.items(), default=[]):
            lid = f"team:{role}"
            nodes.append(SpaceNode(lid, "leader", getattr(leader, "name", role),
                                   level=3, group=role, size=12))
            for tmpl in templates_for(role):
                wid = f"team:{role}:{tmpl.name}"
                nodes.append(SpaceNode(wid, "worker", tmpl.name, level=3, group=role, size=6))
                edges.append(SpaceEdge(lid, wid, "owns"))
        return nodes, edges

    # ── Level 4: Agent ──────────────────────────────────────────────────────────
    def _agent(self):
        nodes, edges = [], []
        for role, leader in safe_call("leaders", lambda: self.society.leaders.items(), default=[]):
            nodes.append(SpaceNode(f"agent:{role}", "leader", getattr(leader, "name", role),
                                   level=4, group=role, size=12))
        for rep in safe_call("rep", lambda: self.society.reputation.top_templates(20), default=[]):
            nodes.append(SpaceNode(f"agent:tmpl:{rep['template']}", "worker",
                                   f"{rep['template']} ({rep['score']:.2f})", level=4,
                                   group="workers", size=6 + 10 * rep["score"],
                                   meta={"score": rep["score"]}))
        return nodes, edges

    # ── Level 5: Task ───────────────────────────────────────────────────────────
    def _task(self):
        nodes, edges = [], []
        for ev in safe_call("life", lambda: self.society.store.lifecycle(50), default=[]):
            nid = f"task:{ev['id']}"
            nodes.append(SpaceNode(nid, "task", f"{ev['event']}:{ev['agent_id'][:6]}",
                                   level=5, group=ev["event"], size=5))
        return nodes, edges

    # ── Level 6: Thought Chain ──────────────────────────────────────────────────
    def _thought_chain(self, focus):
        nodes, edges = [], []
        sim = self.simulations.get(focus) if (self.simulations and focus) else None
        if sim is not None:
            prev = None
            for step in sim.steps:
                nid = f"thought:{sim.id}:{step.index}"
                nodes.append(SpaceNode(nid, "decision", f"step {step.index}", level=6,
                                       group="reasoning", size=6, meta=step.metrics))
                if prev:
                    edges.append(SpaceEdge(prev, nid, "then"))
                prev = nid
        return nodes, edges

    # ── helpers ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _count(fn) -> int:
        return safe_call("count", fn, default=0) or 0

    def _model_count(self) -> int:
        from core.infra.model_registry import get_model_registry
        return get_model_registry().health().get("total", 0)
