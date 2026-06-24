"""
core/observability — FRIDAY 4.0 observability layer.

Trace IDs, the Decision Log, and structured logging — the substrate that makes
FRIDAY explainable. Import is side-effect free.

    from core.observability import start_trace, get_decision_log
    trace = start_trace("turn")
    get_decision_log().log(trace_id=trace.trace_id, intent="question", ...)
"""

from .tracing import (
    Trace,
    start_trace,
    current_trace,
    get_trace_id,
    new_trace_id,
    clear_trace,
)
from .decision_log import DecisionLog, get_decision_log
from .logging_setup import configure, JsonFormatter

__all__ = [
    "Trace",
    "start_trace",
    "current_trace",
    "get_trace_id",
    "new_trace_id",
    "clear_trace",
    "DecisionLog",
    "get_decision_log",
    "configure",
    "JsonFormatter",
]
