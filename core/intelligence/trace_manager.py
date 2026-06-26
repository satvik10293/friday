"""
core/intelligence/trace_manager.py — FRIDAY 4.0 (M12)
The trace manager (Part 11). Records every reasoning session — timestamp, goal,
context summary, memory used, models, agents, reasoning, confidence, outcome,
execution time — to a searchable store. Full provenance for "why did FRIDAY decide
this?".
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from .base import new_id
from .store import IntelligenceStore


@dataclass
class ReasoningTrace:
    id: str = field(default_factory=new_id)
    ts: float = field(default_factory=time.time)
    goal: str = ""
    task: str = ""
    models: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    confidence: float = 0.0
    outcome: str = ""
    execution_ms: float = 0.0
    data: dict = field(default_factory=dict)     # context summary, reasoning, strategy

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class TraceManager:
    def __init__(self, store: Optional[IntelligenceStore] = None) -> None:
        self._store = store

    def start(self, goal: str, task: str, *, context: Optional[dict] = None) -> ReasoningTrace:
        tr = ReasoningTrace(goal=goal, task=task)
        if context is not None:
            tr.data["context_summary"] = {
                "memories": len(context.get("memories", [])),
                "knowledge": len(context.get("knowledge", [])),
                "tokens": context.get("_tokens", 0)}
        return tr

    def finish(self, trace: ReasoningTrace, *, outcome: str, confidence: float,
               models: list, execution_ms: float, agents: Optional[list] = None,
               reasoning: Optional[dict] = None) -> ReasoningTrace:
        trace.outcome = outcome
        trace.confidence = round(confidence, 4)
        trace.models = list(models)
        trace.agents = list(agents or [])
        trace.execution_ms = round(execution_ms, 3)
        if reasoning is not None:
            trace.data["reasoning"] = reasoning
        if self._store is not None:
            self._store.save_trace(trace.to_dict())
        return trace

    def get(self, trace_id: str) -> Optional[dict]:
        return self._store.get_trace(trace_id) if self._store else None

    def search(self, query: str = "", *, task: Optional[str] = None,
               limit: int = 50) -> list[dict]:
        return self._store.search_traces(query, task=task, limit=limit) if self._store else []

    def recent(self, limit: int = 20) -> list[dict]:
        return self.search(limit=limit)
