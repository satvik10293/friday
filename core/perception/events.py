"""
core/perception/events.py — FRIDAY 4.0 (M6)
Perception event vocabulary. These are str-valued so they work directly as keys on
the M1 runtime bus (like GoalEvent/ExecEvent), giving perception a first-class
event vocabulary without modifying the legacy Signal enum.
"""

from __future__ import annotations

from enum import Enum


class PerceptionEvent(str, Enum):
    RECEIVED = "observation.received"
    CHANGED = "observation.changed"
    IGNORED = "observation.ignored"
    PROMOTED = "observation.promoted"
    ARCHIVED = "observation.archived"
