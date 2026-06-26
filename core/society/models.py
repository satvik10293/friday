"""
core/society/models.py — FRIDAY 4.0 (M11)
Pure data models for the agent society. No I/O.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


def _id() -> str:
    return uuid.uuid4().hex[:12]


class AgentKind(str, Enum):
    EXECUTIVE = "executive"
    COORDINATOR = "coordinator"     # the Passive Brain
    LEADER = "leader"
    WORKER = "worker"


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    DONE = "done"
    FAILED = "failed"
    DESTROYED = "destroyed"


class TaskStatus(str, Enum):
    PENDING = "pending"
    DECOMPOSED = "decomposed"
    RUNNING = "running"
    VALIDATED = "validated"
    MERGED = "merged"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str = field(default_factory=_id)
    description: str = ""
    domain: str = ""                # LeaderRole value (or "" → auto-select)
    payload: dict = field(default_factory=dict)
    status: str = TaskStatus.PENDING.value
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class SubTask:
    id: str = field(default_factory=_id)
    task_id: str = ""
    template: str = ""              # worker template name
    target: str = ""               # picklable worker function name (society.worker_tasks)
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    status: str = AgentStatus.IDLE.value

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class WorkerResult:
    subtask_id: str
    template: str
    ok: bool
    value: Any = None
    error: str = ""
    duration_ms: float = 0.0
    cpu_ms: float = 0.0
    mode: str = "process"

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class TaskResult:
    task_id: str
    ok: bool
    leader: str = ""
    merged: Any = None
    subresults: list = field(default_factory=list)   # list[WorkerResult]
    workers_spawned: int = 0
    workers_destroyed: int = 0
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["subresults"] = [s.to_dict() if hasattr(s, "to_dict") else s
                           for s in self.subresults]
        return d


@dataclass
class Message:
    id: str = field(default_factory=_id)
    frm: str = ""
    to: str = ""
    relay: str = "passive_brain"    # every message hops through the coordinator
    kind: str = "info"
    content: dict = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class AgentRecord:
    id: str = field(default_factory=_id)
    kind: str = AgentKind.WORKER.value
    role: str = ""                  # leader role or worker template
    name: str = ""
    status: str = AgentStatus.IDLE.value
    created_at: float = field(default_factory=time.time)
    destroyed_at: Optional[float] = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)
