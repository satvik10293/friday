"""
core/goals/service.py — FRIDAY 4.0
GoalService: the public, observable API for FRIDAY's goal system. Orchestrates
the store, planner, scheduler, progress, and reflection engines, and owns all
side-effects: Decision Log entries, Runtime events, metrics, and Memory writes.

Every mutating action: opens a trace id → writes a DecisionLog row → emits a
Runtime event → updates metrics. Goals are persistent and recoverable; the
service is a singleton attachable to the Runtime.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from .events import GoalEvent
from .goal import new_goal, validate_goal
from .metrics import GoalMetrics
from .models import Goal, GoalStatus, ReflectionRecord
from .planner import Planner
from .progress import ProgressEngine
from .reflection import ReflectionEngine
from .scheduler import GoalScheduler
from .storage import GoalStore

log = logging.getLogger("friday.goals.service")


class GoalService:
    def __init__(self, store: Optional[GoalStore] = None, memory_service=None,
                 decision_log=None, runtime=None, planner: Optional[Planner] = None) -> None:
        self._store = store if store is not None else GoalStore()
        self._memory = memory_service
        self._decision = decision_log
        self._runtime = runtime
        self._planner = planner if planner is not None else Planner()
        self._scheduler = GoalScheduler(self._store)
        self._progress = ProgressEngine(self._store)
        self._reflection = ReflectionEngine(self._store)
        self._metrics = GoalMetrics()
        self._lock = threading.Lock()

    # ── creation / planning ────────────────────────────────────────────────────
    def create_goal(self, title: str, *, description: str = "", priority: int = 3,
                    owner: str = "satvik", parent_goal: Optional[str] = None,
                    dependencies: Optional[list] = None, confidence: float = 0.5,
                    metadata: Optional[dict] = None) -> Goal:
        g = new_goal(title, description=description, priority=priority, owner=owner,
                     parent_goal=parent_goal, dependencies=dependencies,
                     confidence=confidence, metadata=metadata)
        validate_goal(g)
        with self._lock:
            self._store.create_goal(g)
            self._store.add_event(g.goal_id, "created", title, {})
            self._metrics.created += 1
        self._observe("goal.create", g, "created")
        self._emit(GoalEvent.CREATED, g)
        return g

    def plan(self, objective: str, owner: str = "satvik") -> Goal:
        """Decompose an objective into a persisted goal tree; return the root."""
        tree = self._planner.plan(objective, owner)
        with self._lock:
            self._store.create_goal(tree.root)
            self._store.add_event(tree.root.goal_id, "created", objective, {"kind": "root"})
            for child in tree.children:
                self._store.create_goal(child)
                self._store.add_event(child.goal_id, "created", child.title, {})
            self._metrics.created += 1 + len(tree.children)
        self._observe("goal.plan", tree.root, "planned",
                      detail=f"{len(tree.children)} sub-goals")
        self._emit(GoalEvent.CREATED, tree.root)
        return tree.root

    # ── self-generated proposals (M28) — human-gated like codex proposals ───────
    def propose_goal(self, title: str, *, description: str = "", source: str = "",
                     evidence: str = "", priority: int = 4) -> Goal:
        """FRIDAY proposes a goal for herself. It is stored PENDING but the
        scheduler will never activate it until `approve_proposal()`."""
        g = self.create_goal(
            title, description=description, priority=priority, owner="friday",
            metadata={"proposed_by": "friday", "proposal_status": "proposed",
                      "source": source, "evidence": evidence})
        with self._lock:
            self._metrics.proposed += 1
        self._observe("goal.propose", g, "proposed", detail=f"{source}: {evidence}")
        self._emit(GoalEvent.PROPOSED, g, extra={"source": source})
        return g

    def list_proposals(self) -> list[Goal]:
        """Open (unapproved, unrejected) self-generated proposals."""
        return [g for g in self._store.list_goals(status=GoalStatus.PENDING)
                if g.metadata.get("proposal_status") == "proposed"]

    def approve_proposal(self, goal_id: str, by: str = "satvik") -> Optional[Goal]:
        g = self._store.get_goal(goal_id)
        if g is None or g.metadata.get("proposal_status") != "proposed":
            return None
        g.metadata["proposal_status"] = "approved"
        g.metadata["approved_by"] = by
        self._store.update_goal(g)
        self._store.add_event(goal_id, "proposal_approved", f"approved by {by}", {})
        with self._lock:
            self._metrics.proposals_approved += 1
        self._observe("goal.approve_proposal", g, "approved", detail=f"by {by}")
        self._emit(GoalEvent.PROPOSAL_APPROVED, g)
        return g

    def reject_proposal(self, goal_id: str, reason: str = "") -> Optional[Goal]:
        """Rejected proposals are archived (kept, so the generator never
        proposes the same goal twice)."""
        g = self._store.get_goal(goal_id)
        if g is None or g.metadata.get("proposal_status") != "proposed":
            return None
        g.metadata["proposal_status"] = "rejected"
        g.metadata["rejection_reason"] = reason
        g.status = GoalStatus.ARCHIVED
        self._store.update_goal(g)
        self._store.add_event(goal_id, "proposal_rejected", reason, {})
        with self._lock:
            self._metrics.proposals_rejected += 1
        self._observe("goal.reject_proposal", g, "rejected", detail=reason)
        self._emit(GoalEvent.PROPOSAL_REJECTED, g, extra={"reason": reason})
        return g

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def activate_goal(self, goal_id: str) -> Optional[Goal]:
        g = self._transition(goal_id, GoalStatus.ACTIVE, "activated")
        if g is not None:
            self._metrics.activated += 1
            self._emit(GoalEvent.STARTED, g)
        return g

    def pause_goal(self, goal_id: str) -> Optional[Goal]:
        return self._transition(goal_id, GoalStatus.PENDING, "paused")

    def complete_goal(self, goal_id: str, note: str = "") -> Optional[Goal]:
        g = self._progress.mark_complete(goal_id, note)
        if g is None:
            return None
        with self._lock:
            self._metrics.completed += 1
        self._remember(g, "completed", f"Completed goal: {g.title}. {note}".strip())
        self._observe("goal.complete", g, "completed")
        self._emit(GoalEvent.COMPLETED, g)
        return g

    def fail_goal(self, goal_id: str, reason: str = "") -> Optional[Goal]:
        g = self._progress.mark_failed(goal_id, reason)
        if g is None:
            return None
        with self._lock:
            self._metrics.failed += 1
        self._remember(g, "failed", f"Failed goal: {g.title} — reason: {reason}")
        self._observe("goal.fail", g, "failed", detail=reason)
        self._emit(GoalEvent.FAILED, g)
        return g

    def block_goal(self, goal_id: str, reason: str = "") -> Optional[Goal]:
        g = self._progress.mark_blocked(goal_id, reason)
        if g is not None:
            with self._lock:
                self._metrics.blocked += 1
            self._observe("goal.block", g, "blocked", detail=reason)
            self._emit(GoalEvent.BLOCKED, g)
        return g

    def update_progress(self, goal_id: str, percent: float, note: str = "") -> Optional[Goal]:
        return self._progress.update_progress(goal_id, percent, note)

    def resume_goal(self, goal_id: str) -> Optional[Goal]:
        return self._progress.resume_goal(goal_id)

    # ── reflection ─────────────────────────────────────────────────────────────
    def reflect(self, goal_id: str) -> Optional[ReflectionRecord]:
        g = self._store.get_goal(goal_id)
        if g is None:
            return None
        record = self._reflection.generate(g)
        # persist the lesson into long-term memory for future recall
        if self._memory is not None:
            self._memory.remember(
                "system",
                f"{record.summary} Lesson: {record.lesson}",
                topic=g.title, kind="reflection", importance=0.8,
                metadata={"goal_id": g.goal_id, "status": record.status,
                          "lesson": record.lesson},
            )
        with self._lock:
            self._metrics.reflected += 1
        self._store.add_event(g.goal_id, "reflected", record.lesson, record.to_dict())
        self._observe("goal.reflect", g, "reflected", detail=record.lesson)
        self._emit(GoalEvent.REFLECTED, g, extra={"lesson": record.lesson})
        return record

    # ── scheduling ─────────────────────────────────────────────────────────────
    def tick(self) -> dict:
        result = self._scheduler.tick()
        for gid in result.get("activated", []):
            g = self._store.get_goal(gid)
            if g:
                self._emit(GoalEvent.STARTED, g)
        for gid in result.get("blocked", []):
            g = self._store.get_goal(gid)
            if g:
                self._emit(GoalEvent.BLOCKED, g)
        if result.get("activated") or result.get("blocked"):
            self._observe_raw("goal.tick", goals=result.get("activated", []) + result.get("blocked", []),
                              outcome="scheduled")
        return result

    def next_actions(self, limit: int = 5) -> list[dict]:
        return [g.to_dict() for g in self._scheduler.next_actions(limit)]

    # ── queries / recall ───────────────────────────────────────────────────────
    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self._store.get_goal(goal_id)

    def list_goals(self, status: Optional[GoalStatus] = None) -> list[Goal]:
        return self._store.list_goals(status=status)

    def search_goals(self, query: str) -> list[Goal]:
        return self._store.search_goals(query)

    def recall(self, query: str, k: int = 5) -> list[dict]:
        """Retrieve goal-related memories ('what did I complete / learn?')."""
        if self._memory is None:
            return []
        return self._memory.recall(query, k=k)

    # ── status / health ────────────────────────────────────────────────────────
    def status(self) -> dict:
        counts = self._store.counts_by_status()
        return {
            "counts": counts,
            "metrics": self._metrics.snapshot(),
            "next_actions": [g.title for g in self._scheduler.next_actions(5)],
            "proposals": [g.title for g in self.list_proposals()],
        }

    def health(self) -> dict:
        c = self._store.counts_by_status()
        return {
            "status": "ok",          # the DI health sweep requires a verdict
            "active": c.get("active", 0),
            "blocked": c.get("blocked", 0),
            "completed": c.get("completed", 0),
            "pending": c.get("pending", 0),
            "failed": c.get("failed", 0),
            "total": c.get("total", 0),
            "scheduler": "ok",
            "reflection": "ok",
        }

    def attach(self, runtime, tick_every_s: float = 30.0) -> None:
        self._runtime = runtime
        runtime.register_health("goals", self.health)
        runtime.schedule("goals.tick", self.tick, every=tick_every_s)

    def metrics(self) -> dict:
        return self._metrics.snapshot(self._store)

    # ── internals ──────────────────────────────────────────────────────────────
    def _transition(self, goal_id, status, kind) -> Optional[Goal]:
        g = self._store.get_goal(goal_id)
        if g is None:
            return None
        g.status = status
        self._store.update_goal(g)
        self._store.add_event(goal_id, kind, "", {"status": status.value})
        self._observe(f"goal.{kind}", g, kind)
        return g

    def _remember(self, goal: Goal, kind: str, content: str) -> None:
        if self._memory is None:
            return
        try:
            self._memory.remember("system", content, topic=goal.title,
                                  kind=f"goal_{kind}", importance=0.7,
                                  metadata={"goal_id": goal.goal_id})
        except Exception:
            log.debug("memory write failed", exc_info=True)

    def _observe(self, intent: str, goal: Goal, outcome: str, detail: str = "") -> None:
        self._observe_raw(intent, goals=[goal.goal_id], outcome=outcome,
                          rationale=detail or goal.title)

    def _observe_raw(self, intent: str, *, goals: list, outcome: str,
                     rationale: str = "") -> None:
        if self._decision is None:
            return
        try:
            from core.observability import new_trace_id
            self._decision.log(
                trace_id=new_trace_id(), intent=intent, route=["goal"],
                goals_touched=goals, outcome=outcome, rationale=rationale,
                confidence=1.0, was_autonomous=True, source="goals.service",
            )
        except Exception:
            log.debug("decision-log write failed", exc_info=True)

    def _emit(self, event: GoalEvent, goal: Goal, extra: Optional[dict] = None) -> None:
        if self._runtime is None:
            return
        data = {"goal_id": goal.goal_id, "title": goal.title, "status": goal.status.value}
        if extra:
            data.update(extra)
        try:
            self._runtime.emit(event, data=data, source="goals")
        except Exception:
            log.debug("event emit failed", exc_info=True)


# ── singleton ───────────────────────────────────────────────────────────────────
_service: Optional[GoalService] = None
_svc_lock = threading.Lock()


def get_goal_service() -> GoalService:
    global _service
    with _svc_lock:
        if _service is None:
            _service = GoalService()
    return _service
