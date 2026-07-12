"""
core/simulation/sandbox.py — FRIDAY 4.0 (M11)
The simulation sandbox — the safety boundary (Parts 9 & 13). Each simulation gets
its own self-contained virtual world (virtual agents / goals / knowledge / tasks),
held purely in memory. The sandbox **cannot** reference production services:
attempting to put a production-like object (anything exposing a store/conn/DB or a
known production method) into it raises `SandboxViolation`. Simulations therefore
can never read or modify real databases, goals, memories, knowledge, or user data.
"""

from __future__ import annotations

from typing import Any

from .models import VirtualAgent, VirtualGoal, VirtualKnowledge, VirtualTask


class SandboxViolation(RuntimeError):
    """Raised when something tries to cross the sandbox isolation boundary."""


# Attribute/method names that betray a production object sneaking into the sandbox.
_PROD_MARKERS = ("conn", "_conn", "store", "_store", "remember_knowledge",
                 "create_goal", "remember", "save_profile", "execute", "cursor",
                 "knowledge_service", "goal_service", "memory_service")


def _looks_like_production(obj: Any) -> bool:
    if isinstance(obj, (str, int, float, bool, type(None), list, tuple, dict, set)):
        return False
    return any(hasattr(obj, m) for m in _PROD_MARKERS)


class SimulationSandbox:
    """An isolated virtual world. Pure in-memory; no production references allowed."""

    is_sandboxed = True

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._agents: dict[str, VirtualAgent] = {}
        self._goals: dict[str, VirtualGoal] = {}
        self._knowledge: dict[str, VirtualKnowledge] = {}
        self._tasks: dict[str, VirtualTask] = {}

    # ── guarded insertion ───────────────────────────────────────────────────────
    @staticmethod
    def _guard(obj: Any) -> None:
        if _looks_like_production(obj):
            raise SandboxViolation(
                f"refused to admit a production-like object into the sandbox: {type(obj).__name__}")

    def add_agent(self, agent: VirtualAgent) -> VirtualAgent:
        self._guard(agent)
        if not isinstance(agent, VirtualAgent):
            raise SandboxViolation("only VirtualAgent allowed")
        self._agents[agent.id] = agent
        return agent

    def add_goal(self, goal: VirtualGoal) -> VirtualGoal:
        self._guard(goal)
        if not isinstance(goal, VirtualGoal):
            raise SandboxViolation("only VirtualGoal allowed")
        self._goals[goal.id] = goal
        return goal

    def add_knowledge(self, k: VirtualKnowledge) -> VirtualKnowledge:
        self._guard(k)
        if not isinstance(k, VirtualKnowledge):
            raise SandboxViolation("only VirtualKnowledge allowed")
        self._knowledge[k.id] = k
        return k

    def add_task(self, t: VirtualTask) -> VirtualTask:
        self._guard(t)
        if not isinstance(t, VirtualTask):
            raise SandboxViolation("only VirtualTask allowed")
        self._tasks[t.id] = t
        return t

    # ── population helpers ──────────────────────────────────────────────────────
    def spawn_agents(self, n: int, role: str = "worker") -> None:
        for i in range(n):
            self.add_agent(VirtualAgent(name=f"{role}-{i}", role=role))

    # ── views ───────────────────────────────────────────────────────────────────
    @property
    def agents(self) -> list[VirtualAgent]:
        return list(self._agents.values())

    @property
    def goals(self) -> list[VirtualGoal]:
        return list(self._goals.values())

    @property
    def knowledge(self) -> list[VirtualKnowledge]:
        return list(self._knowledge.values())

    @property
    def tasks(self) -> list[VirtualTask]:
        return list(self._tasks.values())

    def counts(self) -> dict:
        return {"agents": len(self._agents), "goals": len(self._goals),
                "knowledge": len(self._knowledge), "tasks": len(self._tasks)}

    def snapshot(self) -> dict:
        return {"agents": len(self._agents),
                "healthy_agents": sum(1 for a in self._agents.values() if a.healthy),
                "goals": len(self._goals), "knowledge": len(self._knowledge),
                "tasks": len(self._tasks),
                "done_tasks": sum(1 for t in self._tasks.values() if t.done)}

    def assert_isolated(self) -> bool:
        """Sanity check: no attribute — nor anything INSIDE the virtual-world
        containers — holds a production-like object. (Checking only the
        container dicts would always pass: dicts are primitives.)"""
        for v in vars(self).values():
            if _looks_like_production(v):
                raise SandboxViolation("sandbox holds a production reference")
            if isinstance(v, dict):
                for item in v.values():
                    if _looks_like_production(item):
                        raise SandboxViolation(
                            "sandbox contains a production-like object: "
                            f"{type(item).__name__}")
        return True
