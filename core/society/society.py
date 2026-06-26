"""
core/society/society.py — FRIDAY 4.0 (M11)
The Agent Society facade — the full hierarchy:

    Executive Brain → Passive Brain Coordinator → Leader Agents → Worker Agents

The Executive decides (prioritise / approve), never works. It hands prioritised
tasks to the Coordinator, which selects a Leader, has it decompose the task, spawns
and destroys workers, and returns merged results — distributed problem solving.
"""

from __future__ import annotations

import logging
from typing import Optional

from core.agent_runtime import ProcessAgentRuntime
from .coordinator import PassiveBrainCoordinator
from .leaders import LEADER_REGISTRY, select_leader
from .models import Task, TaskResult
from .reputation import ReputationSystem
from .scheduler import AgentScheduler
from .store import SocietyStore

log = logging.getLogger("friday.society")


class AgentSociety:
    def __init__(self, store: Optional[SocietyStore] = None, *,
                 runtime: Optional[ProcessAgentRuntime] = None,
                 use_processes: bool = True, max_parallel: int = 4) -> None:
        self._store = store if store is not None else SocietyStore()
        runtime = runtime if runtime is not None else ProcessAgentRuntime(use_processes=use_processes)
        scheduler = AgentScheduler(runtime, max_parallel=max_parallel)
        self.reputation = ReputationSystem(self._store)
        self.coordinator = PassiveBrainCoordinator(
            self._store, scheduler=scheduler, reputation=self.reputation)
        self.leaders = LEADER_REGISTRY

    @property
    def store(self) -> SocietyStore:
        return self._store

    # ── Executive Brain (decides, never works) ──────────────────────────────────
    def prioritize(self, task: Task, priority: int = 3) -> Task:
        task.payload.setdefault("_priority", priority)
        return task

    def approve(self, task: Task) -> bool:
        # the Executive's gate; trivially approve here (hook for human-in-the-loop)
        return True

    # ── distributed problem solving ─────────────────────────────────────────────
    def solve(self, description: str, *, domain: str = "", payload: Optional[dict] = None,
              priority: int = 3) -> TaskResult:
        """Observe → select leader → decompose → spawn workers → parallel → validate
        → merge → destroy. The full society lifecycle for one problem."""
        task = Task(description=description, domain=domain, payload=dict(payload or {}))
        self.prioritize(task, priority)
        if not self.approve(task):
            return TaskResult(task_id=task.id, ok=False, leader="executive")
        leader = select_leader(task)
        return self.coordinator.run_task(task, leader)

    # ── introspection ───────────────────────────────────────────────────────────
    def status(self) -> dict:
        return {
            "hierarchy": ["executive", "passive_brain", "leaders", "workers"],
            "leaders": [{"role": r, "name": l.name} for r, l in self.leaders.items()],
            "active_workers": len(self.coordinator.active_workers()),
            "reputation": self.reputation.top_templates(8),
            **self._store.counts(),
        }

    def health(self) -> dict:
        return {"status": "ok", "leaders": len(self.leaders),
                "coordinator": self.coordinator.health()}

    def close(self) -> None:
        self._store.close()


_society: Optional[AgentSociety] = None


def get_society() -> AgentSociety:
    global _society
    if _society is None:
        _society = AgentSociety()
    return _society
