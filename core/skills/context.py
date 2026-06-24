"""
core/skills/context.py — FRIDAY 4.0
SkillContext: the execution context passed to every skill and the executor.
Carries the trace id and references to the runtime, memory, decision log, and the
caller's role. Skills receive exactly this — never global singletons — so they
stay testable and decoupled.

`user_role` is typed Any to keep this a dependency-free leaf module (the executor
resolves None -> Role.USER); no import of core.security here, by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SkillContext:
    trace_id: Optional[str] = None
    runtime: Any = None
    memory_service: Any = None
    decision_log: Any = None
    working_memory: Any = None
    user_role: Any = None          # core.security.roles.Role (resolved by executor if None)
    caller: str = "system"
    metadata: dict = field(default_factory=dict)

    @classmethod
    def minimal(cls, **kw) -> "SkillContext":
        from core.observability import new_trace_id
        tid = kw.pop("trace_id", None) or new_trace_id()
        return cls(trace_id=tid, **kw)
