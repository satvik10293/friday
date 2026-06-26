"""
core/cognitive_space/models.py — FRIDAY 4.0 (M11)
Data models + visual language for the cognitive universe. Pure data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ZoomLevel(int, Enum):
    UNIVERSE = 1        # entire FRIDAY: goals, knowledge, projects, agents, models, sims
    DOMAIN = 2          # knowledge domains, agent teams, goal clusters
    TEAM = 3            # research/coding/planning/knowledge teams
    AGENT = 4           # individual leader + worker agents
    TASK = 5            # specific assignments, communication, outputs
    THOUGHT_CHAIN = 6   # reasoning steps, knowledge retrieval, decision formation


class VisualKind(str, Enum):
    STAR = "star"               # knowledge
    ATTRACTOR = "attractor"     # goals
    ENTITY = "entity"           # agents
    ENERGY = "energy"           # tasks
    CONVERGENCE = "convergence" # decisions
    UNIVERSE = "universe"       # simulations
    NODE = "node"               # generic


# kind → (visual, colour). The M11 visual language.
VISUAL_LANGUAGE: dict[str, dict] = {
    "knowledge":  {"visual": VisualKind.STAR.value, "color": "#4da3ff"},
    "goal":       {"visual": VisualKind.ATTRACTOR.value, "color": "#ffcc55"},
    "project":    {"visual": VisualKind.ATTRACTOR.value, "color": "#37d39b"},
    "agent":      {"visual": VisualKind.ENTITY.value, "color": "#b48cff"},
    "leader":     {"visual": VisualKind.ENTITY.value, "color": "#d36cff"},
    "worker":     {"visual": VisualKind.ENTITY.value, "color": "#8a6cff"},
    "task":       {"visual": VisualKind.ENERGY.value, "color": "#ff8a5c"},
    "decision":   {"visual": VisualKind.CONVERGENCE.value, "color": "#ff5d6c"},
    "simulation": {"visual": VisualKind.UNIVERSE.value, "color": "#5cf2e0"},
    "model":      {"visual": VisualKind.NODE.value, "color": "#9e9e9e"},
    "domain":     {"visual": VisualKind.NODE.value, "color": "#6fa8ff"},
}


def visual_for(kind: str) -> dict:
    return VISUAL_LANGUAGE.get(kind, {"visual": VisualKind.NODE.value, "color": "#9e9e9e"})


@dataclass
class SpaceNode:
    id: str
    kind: str
    label: str
    level: int = 1
    group: str = ""
    size: float = 6.0
    position: tuple = (0.0, 0.0, 0.0)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        v = visual_for(self.kind)
        return {"id": self.id, "kind": self.kind, "label": self.label,
                "level": self.level, "group": self.group, "size": self.size,
                "position": list(self.position), "visual": v["visual"],
                "color": v["color"], "meta": self.meta}


@dataclass
class SpaceEdge:
    source: str
    target: str
    kind: str = "link"

    def to_dict(self) -> dict:
        return {"source": self.source, "target": self.target, "kind": self.kind}
