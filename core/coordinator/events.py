"""
core/coordinator/events.py — FRIDAY V3 (M17 revision)
Cognitive Coordinator event vocabulary, published on the Runtime event bus.
"""

from __future__ import annotations

from enum import Enum


class CoordinatorEvent(str, Enum):
    REPORT_RECEIVED = "coordinator.report.received"
    REPORTS_MERGED = "coordinator.reports.merged"
    CONFLICT_RESOLVED = "coordinator.conflict.resolved"
    DUPLICATE_REMOVED = "coordinator.duplicate.removed"
    SITUATION_BUILT = "coordinator.situation.built"
    PUBLISHED_TO_EXECUTIVE = "coordinator.published_to_executive"
    CONTEXT_UPDATED = "coordinator.context.updated"
