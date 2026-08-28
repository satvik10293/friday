"""
core/society/coordinator.py — FRIDAY 4.0 (M11)
The Passive Brain Coordinator — the management layer. It spawns workers, schedules
their work, monitors them, merges their results, destroys them, and is the single
relay for all agent communication. It does no heavy work itself; it orchestrates.

Lifecycle it owns for every task:
    decompose (by leader) → spawn workers → parallel work → validate → merge →
    destroy workers → update reputation.
"""

from __future__ import annotations

import time
from typing import Optional

from .bus import COORDINATOR, AgentBus
from .models import (AgentKind, AgentRecord, AgentStatus, SubTask, Task, TaskResult,
                     TaskStatus)
from .reputation import ReputationSystem
from .scheduler import AgentScheduler


class PassiveBrainCoordinator:
    def __init__(self, store, *, scheduler: Optional[AgentScheduler] = None,
                 reputation: Optional[ReputationSystem] = None,
                 bus: Optional[AgentBus] = None) -> None:
        self._store = store
        self._scheduler = scheduler if scheduler is not None else AgentScheduler()
        self._reputation = reputation if reputation is not None else ReputationSystem(store)
        self._bus = bus if bus is not None else AgentBus()

    @property
    def reputation(self) -> ReputationSystem:
        return self._reputation

    @property
    def bus(self) -> AgentBus:
        return self._bus

    # ── communication (the only relay) ──────────────────────────────────────────
    def relay(self, frm: str, to: str, content: Optional[dict] = None,
              kind: str = "info"):
        return self._bus.relay(frm, to, content, kind)

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def spawn_worker(self, leader_name: str, subtask: SubTask) -> AgentRecord:
        rec = AgentRecord(kind=AgentKind.WORKER.value, role=subtask.template,
                          name=subtask.template, status=AgentStatus.BUSY.value)
        self._store.save_agent(rec)
        self._store.add_lifecycle(rec.id, "spawned",
                                  {"template": subtask.template, "by": leader_name})
        self.relay(leader_name, rec.id, {"assign": subtask.template})  # leader→worker via brain
        return rec

    def destroy_worker(self, rec: AgentRecord) -> None:
        rec.status = AgentStatus.DESTROYED.value
        rec.destroyed_at = time.time()
        self._store.save_agent(rec)
        self._store.add_lifecycle(rec.id, "destroyed", {"template": rec.role})

    # ── task execution ──────────────────────────────────────────────────────────
    def run_task(self, task: Task, leader) -> TaskResult:
        t0 = time.perf_counter()
        # 1) decompose (only the leader may create workers)
        subtasks = leader.decompose(task)
        task.status = TaskStatus.DECOMPOSED.value

        # 2) spawn a worker per subtask
        records = [self.spawn_worker(leader.name, st) for st in subtasks]
        task.status = TaskStatus.RUNNING.value

        # 3) parallel work
        results = self._scheduler.dispatch(subtasks)

        # 4) validate + 5) merge
        merged = {}
        all_ok = bool(results)
        for st, res in zip(subtasks, results):
            all_ok = all_ok and res.ok
            if res.ok:
                merged[st.template] = res.value
            # worker→brain result message
            self.relay(self._worker_name(records, st), COORDINATOR,
                       {"ok": res.ok, "template": st.template}, kind="result")
            # 7) reputation update
            self._reputation.record(st.template, success=res.ok,
                                    duration_ms=res.duration_ms or 1.0,
                                    cpu_ms=res.cpu_ms)
        task.status = TaskStatus.MERGED.value

        # 6) destroy all workers
        for rec in records:
            self.destroy_worker(rec)

        result = TaskResult(task_id=task.id, ok=all_ok, leader=leader.name,
                            merged=merged, subresults=results,
                            workers_spawned=len(records), workers_destroyed=len(records),
                            duration_ms=(time.perf_counter() - t0) * 1000.0)
        task.status = TaskStatus.COMPLETED.value if all_ok else TaskStatus.FAILED.value
        self._store.save_task(result)
        return result

    @staticmethod
    def _worker_name(records, subtask) -> str:
        for r in records:
            if r.role == subtask.template:
                return r.id
        return subtask.template

    # ── monitoring ──────────────────────────────────────────────────────────────
    def active_workers(self) -> list[dict]:
        return [a for a in self._store.active_agents() if a["kind"] == AgentKind.WORKER.value]

    def health(self) -> dict:
        return {"status": "ok", "active_workers": len(self.active_workers()),
                "messages": len(self._bus), **self._store.counts()}
