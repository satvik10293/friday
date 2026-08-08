"""
core/harness/task.py — FRIDAY harness (task lifecycle)

A first-class `Task` with an explicit, traceable state machine. Everything the
harness runs is a Task, and every Task walks a bounded lifecycle so its progress
is observable and its transitions are legal by construction (an illegal jump
raises rather than silently corrupting state).

Lifecycle (happy path):
    CREATED → PLANNING → DELEGATING → RUNNING → VERIFYING → COMPLETED

Off-path states:
    RETRYING   — a run/verify failed and the harness is trying again
    ESCALATED  — cannot be resolved safely; awaiting another agent or the user
    FAILED     — terminal failure (honest, not silent)
    CANCELLED  — terminal, cancelled by caller

`FAILED`, `COMPLETED`, and `CANCELLED` are terminal. The transition table is the
single source of truth for what may follow what; the orchestrator drives it and
never sets `.state` directly.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class TaskState(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    DELEGATING = "delegating"
    RUNNING = "running"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    ESCALATED = "escalated"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})

# The legal transition table — the whole contract of the FSM in one place.
_TRANSITIONS: dict[TaskState, frozenset] = {
    TaskState.CREATED: frozenset({TaskState.PLANNING, TaskState.DELEGATING,
                                  TaskState.RUNNING, TaskState.CANCELLED,
                                  TaskState.FAILED}),
    TaskState.PLANNING: frozenset({TaskState.DELEGATING, TaskState.RUNNING,
                                   TaskState.ESCALATED, TaskState.FAILED,
                                   TaskState.CANCELLED}),
    TaskState.DELEGATING: frozenset({TaskState.RUNNING, TaskState.ESCALATED,
                                     TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.RUNNING: frozenset({TaskState.VERIFYING, TaskState.RETRYING,
                                  TaskState.COMPLETED, TaskState.ESCALATED,
                                  TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.VERIFYING: frozenset({TaskState.COMPLETED, TaskState.RETRYING,
                                    TaskState.ESCALATED, TaskState.FAILED,
                                    TaskState.CANCELLED}),
    TaskState.RETRYING: frozenset({TaskState.RUNNING, TaskState.DELEGATING,
                                   TaskState.ESCALATED, TaskState.FAILED,
                                   TaskState.CANCELLED}),
    TaskState.ESCALATED: frozenset({TaskState.RUNNING, TaskState.DELEGATING,
                                    TaskState.COMPLETED, TaskState.FAILED,
                                    TaskState.CANCELLED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class IllegalTransition(RuntimeError):
    """Raised on an attempt to move a Task between states the FSM forbids."""


def new_task_id() -> str:
    return "task-" + uuid.uuid4().hex[:10]


@dataclass
class TaskEvent:
    at: float
    frm: str
    to: str
    note: str = ""


@dataclass
class Task:
    objective: str
    task_id: str = field(default_factory=new_task_id)
    capability: str = "text"
    state: TaskState = TaskState.CREATED
    context: dict = field(default_factory=dict)
    result: Any = None
    error: str = ""
    attempts: int = 0
    provider: str = ""
    tags: dict = field(default_factory=dict)         # caller labels (purpose, source…)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list = field(default_factory=list)

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def can_transition(self, to: TaskState) -> bool:
        return to in _TRANSITIONS.get(self.state, frozenset())

    def transition(self, to: TaskState, *, note: str = "") -> "Task":
        if not self.can_transition(to):
            raise IllegalTransition(
                f"{self.task_id}: {self.state.value} → {to.value} is not permitted")
        self.history.append(TaskEvent(at=time.time(), frm=self.state.value,
                                      to=to.value, note=note))
        self.state = to
        self.updated_at = time.time()
        return self

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def succeeded(self) -> bool:
        return self.state is TaskState.COMPLETED

    @property
    def duration_ms(self) -> float:
        """Wall-clock from creation to the last transition."""
        return (self.updated_at - self.created_at) * 1000.0

    # ── terminal helpers ─────────────────────────────────────────────────────────
    def complete(self, result: Any = None, *, note: str = "") -> "Task":
        if result is not None:
            self.result = result
        return self.transition(TaskState.COMPLETED, note=note)

    def fail(self, error: str = "", *, note: str = "") -> "Task":
        if error:
            self.error = error
        return self.transition(TaskState.FAILED, note=note or error)

    def cancel(self, *, note: str = "") -> "Task":
        return self.transition(TaskState.CANCELLED, note=note)

    def to_dict(self) -> dict:
        return {"task_id": self.task_id, "objective": self.objective,
                "capability": self.capability, "state": self.state.value,
                "attempts": self.attempts, "provider": self.provider,
                "error": self.error, "tags": dict(self.tags),
                "created_at": self.created_at, "updated_at": self.updated_at,
                "duration_ms": round(self.duration_ms, 2),
                "history": [e.__dict__ for e in self.history]}
