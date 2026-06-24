"""
core/observability/tracing.py — FRIDAY 4.0
Trace IDs and per-turn trace context.

Every cognitive turn opens a Trace; the trace id is threaded through the cycle
so logs and the Decision Log can be correlated ("why did FRIDAY do that?").
Uses contextvars so the current trace follows async tasks correctly.
"""

from __future__ import annotations

import contextvars
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

_current: contextvars.ContextVar = contextvars.ContextVar("friday_trace", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Trace:
    trace_id: str
    label: str = ""
    started_at: float = field(default_factory=time.time)
    fields: dict = field(default_factory=dict)

    def set(self, **kw) -> "Trace":
        self.fields.update(kw)
        return self

    def elapsed_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)


def start_trace(label: str = "", trace_id: Optional[str] = None) -> Trace:
    t = Trace(trace_id or new_trace_id(), label=label)
    _current.set(t)
    return t


def current_trace() -> Optional[Trace]:
    return _current.get()


def get_trace_id() -> Optional[str]:
    t = _current.get()
    return t.trace_id if t else None


def clear_trace() -> None:
    _current.set(None)
