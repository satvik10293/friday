"""
core/simulation/models.py — FRIDAY 4.0 (M11)
Pure data models for the simulation engine and its virtual worlds. No I/O.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


def _id() -> str:
    return uuid.uuid4().hex[:12]


class SimulationType(str, Enum):
    ARCHITECTURE = "architecture"
    SOFTWARE_DESIGN = "software_design"
    RESEARCH = "research"
    PROJECT_PLANNING = "project_planning"
    GOAL_ACHIEVEMENT = "goal_achievement"
    AGENT_SOCIETY = "agent_society"
    BUSINESS = "business"
    LEARNING = "learning"
    SCIENTIFIC = "scientific"
    CUSTOM = "custom"


class SimStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


# ── virtual entities (sandbox-only; never production objects) ──────────────────────
@dataclass
class VirtualAgent:
    id: str = field(default_factory=_id)
    name: str = ""
    role: str = "worker"
    healthy: bool = True
    load: float = 0.0


@dataclass
class VirtualGoal:
    id: str = field(default_factory=_id)
    name: str = ""
    progress: float = 0.0


@dataclass
class VirtualKnowledge:
    id: str = field(default_factory=_id)
    title: str = ""
    confidence: float = 0.5


@dataclass
class VirtualTask:
    id: str = field(default_factory=_id)
    name: str = ""
    done: bool = False


# ── scenario / steps / results ────────────────────────────────────────────────────
@dataclass
class Scenario:
    sim_type: str = SimulationType.CUSTOM.value
    name: str = ""
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SimStep:
    index: int
    metrics: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Recommendation:
    text: str = ""
    confidence: float = 0.0
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SimResult:
    sim_id: str
    ok: bool
    final_metrics: dict = field(default_factory=dict)
    recommendation: Optional[Recommendation] = None
    findings: list = field(default_factory=list)
    steps: int = 0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        if self.recommendation is not None:
            d["recommendation"] = self.recommendation.to_dict()
        return d


@dataclass
class Simulation:
    id: str = field(default_factory=_id)
    name: str = ""
    sim_type: str = SimulationType.CUSTOM.value
    scenario: Optional[Scenario] = None
    status: str = SimStatus.CREATED.value
    steps: list = field(default_factory=list)        # list[SimStep]
    result: Optional[SimResult] = None
    parent_id: Optional[str] = None                  # set when forked
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "sim_type": self.sim_type,
                "status": self.status, "steps": len(self.steps),
                "parent_id": self.parent_id, "created_at": self.created_at,
                "result": self.result.to_dict() if self.result else None}
