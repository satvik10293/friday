"""
core/context/context_package.py — FRIDAY 4.0 (M5)
ContextPackage: the assembled, ranked reasoning context for one cognitive turn.
This is the single object the Reasoner / Executive Brain (and, later, an LLM)
consume — so what FRIDAY "had in mind" for any decision is fully inspectable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ContextPackage:
    query: str = ""
    memories: list = field(default_factory=list)      # list[dict] (with score)
    goals: list = field(default_factory=list)         # list[dict]
    lessons: list = field(default_factory=list)       # list[dict] (reflections)
    focus_items: list = field(default_factory=list)   # list[dict] (AttentionScore dicts)
    world: dict = field(default_factory=dict)         # world-model summary
    confidence: float = 0.0
    trace_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    @property
    def is_empty(self) -> bool:
        return not (self.memories or self.goals or self.lessons or self.focus_items)

    def summary(self) -> str:
        return (f"context(query={self.query!r}, mem={len(self.memories)}, "
                f"goals={len(self.goals)}, lessons={len(self.lessons)}, "
                f"focus={len(self.focus_items)}, conf={self.confidence:.2f})")

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "memories": self.memories,
            "goals": self.goals,
            "lessons": self.lessons,
            "focus_items": self.focus_items,
            "world": self.world,
            "confidence": self.confidence,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
        }
