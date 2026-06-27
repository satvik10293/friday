"""
core/cognition_core/events.py — FRIDAY 6.0 (M13)
Event vocabulary for the cognition core. str-valued so they double as keys on the M1
runtime bus (the pattern used by GoalEvent/ExecEvent/KnowledgeEvent), without
touching the frozen 3.0 Signal enum.
"""

from __future__ import annotations

from enum import Enum


class CognitionEvent(str, Enum):
    ENTITY_CREATED = "entity.created"
    ENTITY_RESOLVED = "entity.resolved"
    ENTITY_MERGED = "entity.merged"
    BELIEF_ASSERTED = "belief.asserted"
    BELIEF_REVISED = "belief.revised"
    BELIEF_RETRACTED = "belief.retracted"
    BELIEF_CONFLICT = "belief.conflict"
