"""
core/society/leaders.py — FRIDAY 4.0 (M11)
The eight permanent Leader agents. Leaders own a domain, stay resident, and — when
the Coordinator hands them a task — **decompose** it into worker subtasks. Only
Leaders create workers (and only via the Coordinator); Leaders never run the heavy
work themselves.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from .models import SubTask, Task
from .workers import WORKER_TEMPLATES, WorkerTemplate, get_template


class LeaderRole(str, Enum):
    RESEARCH = "research"
    CODING = "coding"
    PLANNING = "planning"
    KNOWLEDGE = "knowledge"
    SECURITY = "security"
    CREATIVE = "creative"
    AUTOMATION = "automation"
    SIMULATION = "simulation"


class LeaderAgent:
    """A resident domain leader. Subclasses define `plan()`; the base turns the
    plan into SubTasks and provides a safe fallback."""

    role: LeaderRole = LeaderRole.RESEARCH
    name: str = "Leader"

    def __init__(self, role: Optional[LeaderRole] = None, name: str = "") -> None:
        if role is not None:
            self.role = role
        self.name = name or f"{self.role.value.capitalize()} Leader"

    def plan(self, task: Task) -> list[tuple]:
        """Return [(template_name, args, kwargs), ...]. Overridden per leader."""
        return []

    def decompose(self, task: Task) -> list[SubTask]:
        steps = self.plan(task)
        if not steps:
            # fallback: summarise the task description with a research worker
            steps = [("Scientific Researcher", (task.description or "no description",), {})]
        out = []
        for tname, args, kwargs in steps:
            tmpl: WorkerTemplate = get_template(tname)
            out.append(SubTask(task_id=task.id, template=tname,
                               target=tmpl.target_name, args=tuple(args),
                               kwargs=dict(kwargs)))
        return out


class ResearchLeader(LeaderAgent):
    role = LeaderRole.RESEARCH
    def plan(self, task):
        p, steps = task.payload, []
        if p.get("text"):
            steps.append(("Scientific Researcher", (p["text"],), {}))
        if p.get("api"):
            steps.append(("API Researcher", (p["api"],), {}))
        return steps


class CodingLeader(LeaderAgent):
    role = LeaderRole.CODING
    def plan(self, task):
        p, steps = task.payload, []
        if p.get("code"):
            steps.append(("Python Debugger", (p["code"],), {}))
        if p.get("architecture"):
            steps.append(("Architecture Reviewer", (p["architecture"],), {}))
        return steps


class PlanningLeader(LeaderAgent):
    role = LeaderRole.PLANNING
    def plan(self, task):
        p, steps = task.payload, []
        if p.get("dependencies") is not None:
            steps.append(("Dependency Analyzer", (p["dependencies"],), {}))
        if p.get("expression"):
            steps.append(("Math Solver", (p["expression"],), {}))
        return steps


class KnowledgeLeader(LeaderAgent):
    role = LeaderRole.KNOWLEDGE
    def plan(self, task):
        p = task.payload
        topic = p.get("topic", task.description or "Knowledge")
        return [("Documentation Writer", (topic, p.get("points", [])), {})]


class SecurityLeader(LeaderAgent):
    role = LeaderRole.SECURITY
    def plan(self, task):
        p = task.payload
        if p.get("architecture"):
            return [("Architecture Reviewer", (p["architecture"],), {})]
        return []


class CreativeLeader(LeaderAgent):
    role = LeaderRole.CREATIVE
    def plan(self, task):
        p = task.payload
        return [("Documentation Writer",
                 (p.get("topic", task.description or "Idea"), p.get("ideas", [])), {})]


class AutomationLeader(LeaderAgent):
    role = LeaderRole.AUTOMATION
    def plan(self, task):
        p = task.payload
        if p.get("steps") is not None:
            return [("Dependency Analyzer", (p["steps"],), {})]
        return []


class SimulationLeader(LeaderAgent):
    role = LeaderRole.SIMULATION
    def plan(self, task):
        p = task.payload
        if p.get("metrics") is not None:
            return [("Simulation Evaluator", (p["metrics"],), {})]
        return []


LEADER_REGISTRY: dict[str, LeaderAgent] = {
    l.role.value: l for l in [
        ResearchLeader(), CodingLeader(), PlanningLeader(), KnowledgeLeader(),
        SecurityLeader(), CreativeLeader(), AutomationLeader(), SimulationLeader(),
    ]
}

# keyword → domain hints for auto-selection when a task names no domain
_KEYWORDS = {
    "code": "coding", "bug": "coding", "debug": "coding", "architecture": "coding",
    "research": "research", "paper": "research", "api": "research",
    "plan": "planning", "depend": "planning", "math": "planning", "schedule": "planning",
    "document": "knowledge", "knowledge": "knowledge", "note": "knowledge",
    "security": "security", "auth": "security", "vulnerab": "security",
    "idea": "creative", "design": "creative", "creative": "creative",
    "automat": "automation", "workflow": "automation",
    "simulat": "simulation", "scale": "simulation", "stress": "simulation",
}


def select_leader(task: Task) -> LeaderAgent:
    """Pick the leader for a task: explicit domain wins; else keyword match on the
    description; else the Research leader."""
    if task.domain and task.domain in LEADER_REGISTRY:
        return LEADER_REGISTRY[task.domain]
    text = f"{task.description} {' '.join(map(str, task.payload.keys()))}".lower()
    for kw, domain in _KEYWORDS.items():
        if kw in text:
            return LEADER_REGISTRY[domain]
    return LEADER_REGISTRY["research"]
