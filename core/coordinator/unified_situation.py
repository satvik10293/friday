"""
core/coordinator/unified_situation.py — FRIDAY V3 (M17 revision)
The Unified Situation — the Cognitive Coordinator's output and the ONLY thing the
Executive Brain consumes. It is the merged, de-duplicated, conflict-resolved synthesis of
the Situation Reports the brains published this cycle: one coherent picture of "what is
happening" with its source brains, confidence, priority, and recommended action.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


def new_situation_id() -> str:
    return "US_" + uuid.uuid4().hex[:12]


@dataclass
class UnifiedSituation:
    summary: str = ""
    confidence: float = 0.5
    priority: float = 0.5
    category: str = "status"
    source_brains: list = field(default_factory=list)
    reports: list = field(default_factory=list)           # contributing report dicts
    context: dict = field(default_factory=dict)
    conflicts: list = field(default_factory=list)
    recommended_action: Optional[str] = None
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=new_situation_id)

    # alias so the reused hub Timeline (keys on `event_category`) accepts us directly
    @property
    def event_category(self) -> str:
        return self.category

    def signature(self) -> str:
        return f"{self.category}|{self.summary}"

    def to_dict(self) -> dict:
        return {"id": self.id, "timestamp": self.timestamp, "session_id": self.session_id,
                "summary": self.summary, "confidence": round(float(self.confidence), 4),
                "priority": round(float(self.priority), 4), "category": self.category,
                "source_brains": self.source_brains, "reports": self.reports,
                "context": self.context, "conflicts": self.conflicts,
                "recommended_action": self.recommended_action}
