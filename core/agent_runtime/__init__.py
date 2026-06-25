"""
core/agent_runtime/ — FRIDAY 4.0 (M10)
Process-based agent runtime. Closes the architecture review's "GIL-bound, threads
not processes" scaling risk and prepares for M11's agent teams: agents run in
*separate OS processes* (true parallelism, crash isolation), with full lifecycle
metrics (spawn time, lifetime, memory, CPU, failure/completion rate).

Resilient by design: if process spawning is unavailable, the runtime degrades to an
isolated in-process execution rather than failing. Side-effect-free to import
(no process is started at import).
"""

from __future__ import annotations

from .models import AgentResult, AgentSpec, RuntimeMetrics
from .runtime import ProcessAgentRuntime, get_agent_runtime

__all__ = ["ProcessAgentRuntime", "get_agent_runtime", "AgentSpec", "AgentResult",
           "RuntimeMetrics"]
