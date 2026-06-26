"""
core/cognitive_space/search.py — FRIDAY 4.0 (M11)
Global search across the whole universe (Part 11): knowledge, goals, projects,
agents, tasks, models, simulations, events. Each hit carries a camera-focus target
(zoom level + node id) so Mission Control can fly straight to it. Resilient — a
missing subsystem simply contributes no hits.
"""

from __future__ import annotations

from typing import Optional

from core.mission_control.resilience import safe_call
from .models import ZoomLevel


class GlobalSearch:
    def __init__(self, *, knowledge_service=None, goal_service=None, society=None,
                 simulation_service=None, user_model=None) -> None:
        self.knowledge = knowledge_service
        self.goals = goal_service
        self.society = society
        self.simulations = simulation_service
        self.user_model = user_model

    def search(self, query: str, *, limit: int = 30) -> dict:
        q = (query or "").strip().lower()
        hits: list[dict] = []
        if q:
            hits += self._knowledge(q)
            hits += self._goals(q)
            hits += self._projects(q)
            hits += self._agents(q)
            hits += self._simulations(q)
            hits += self._models(q)
        return {"query": query, "count": len(hits[:limit]), "results": hits[:limit]}

    def _hit(self, kind, nid, label, level, group=""):
        return {"kind": kind, "id": nid, "label": label,
                "focus": {"level": int(level), "node_id": nid, "group": group}}

    def _knowledge(self, q):
        def go():
            out = []
            for e in self.knowledge.search_knowledge(q, k=8):
                out.append(self._hit("knowledge", f"domain:know:{e.category}",
                                     e.title, ZoomLevel.DOMAIN.value, e.category))
            return out
        return safe_call("search.knowledge", go, default=[]) or []

    def _goals(self, q):
        def go():
            out = []
            for g in self.goals.list_goals():
                if q in g.title.lower():
                    st = g.status.value if hasattr(g.status, "value") else str(g.status)
                    out.append(self._hit("goal", f"domain:goals:{st}", g.title,
                                         ZoomLevel.DOMAIN.value, st))
            return out
        return safe_call("search.goals", go, default=[]) or []

    def _projects(self, q):
        def go():
            out = []
            for p in self.user_model.projects.list():
                if q in p.name.lower():
                    out.append(self._hit("project", f"universe:projects", p.name,
                                         ZoomLevel.UNIVERSE.value))
            return out
        return safe_call("search.projects", go, default=[]) or []

    def _agents(self, q):
        def go():
            out = []
            for role, leader in self.society.leaders.items():
                if q in role or q in getattr(leader, "name", "").lower():
                    out.append(self._hit("leader", f"agent:{role}",
                                         getattr(leader, "name", role), ZoomLevel.AGENT.value, role))
            from core.society.workers import WORKER_TEMPLATES
            for name in WORKER_TEMPLATES:
                if q in name.lower():
                    out.append(self._hit("worker", f"agent:tmpl:{name}", name,
                                         ZoomLevel.AGENT.value, "workers"))
            return out
        return safe_call("search.agents", go, default=[]) or []

    def _simulations(self, q):
        def go():
            out = []
            for s in self.simulations.list():
                if q in (s.get("name", "") or "").lower() or q in (s.get("sim_type", "") or ""):
                    out.append(self._hit("simulation", f"sim:{s['id']}", s.get("name", s["id"]),
                                         ZoomLevel.THOUGHT_CHAIN.value))
            return out
        return safe_call("search.sims", go, default=[]) or []

    def _models(self, q):
        def go():
            from core.infra.model_registry import get_model_registry
            out = []
            for m in get_model_registry().list_models():
                if q in m.get("name", "").lower() or q in m.get("category", "").lower():
                    out.append(self._hit("model", "universe:models", m["name"],
                                         ZoomLevel.UNIVERSE.value))
            return out
        return safe_call("search.models", go, default=[]) or []
