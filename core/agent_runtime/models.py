"""
core/agent_runtime/models.py — FRIDAY 4.0 (M10)
Data models for the process-based agent runtime. Pure data, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AgentSpec:
    """A unit of agent work to run in its own process. `target` must be a
    picklable (module-level) callable so it can cross the process boundary."""
    name: str
    target: Callable
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    timeout: Optional[float] = None


@dataclass
class AgentResult:
    name: str
    ok: bool
    value: Any = None
    error: str = ""
    pid: Optional[int] = None
    spawn_ms: float = 0.0          # time from launch to process started
    lifetime_ms: float = 0.0       # total wall time until result/termination
    cpu_ms: float = 0.0            # CPU time consumed by the child
    peak_memory_mb: float = 0.0
    exit_code: Optional[int] = None
    timed_out: bool = False
    mode: str = "process"          # process | in_process

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class RuntimeMetrics:
    spawns: int = 0
    completions: int = 0
    failures: int = 0
    timeouts: int = 0
    total_spawn_ms: float = 0.0
    total_lifetime_ms: float = 0.0

    def record(self, result: AgentResult) -> None:
        self.spawns += 1
        self.total_spawn_ms += result.spawn_ms
        self.total_lifetime_ms += result.lifetime_ms
        if result.timed_out:
            self.timeouts += 1
        if result.ok:
            self.completions += 1
        else:
            self.failures += 1

    def snapshot(self) -> dict:
        n = self.spawns or 1
        return {
            "spawns": self.spawns,
            "completions": self.completions,
            "failures": self.failures,
            "timeouts": self.timeouts,
            "completion_rate": round(self.completions / n, 4),
            "failure_rate": round(self.failures / n, 4),
            "avg_spawn_ms": round(self.total_spawn_ms / n, 3),
            "avg_lifetime_ms": round(self.total_lifetime_ms / n, 3),
        }
