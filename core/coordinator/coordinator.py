"""
core/coordinator/coordinator.py — FRIDAY V3 (M17 revision)
The Cognitive Coordinator — the successor to the Perception Hub, raised to the level of
*situation reports* rather than raw observations. It subscribes to the Situation Report
Bus, and each cycle it:

  • merges related reports from different brains into one picture,
  • resolves conflicting observations (higher confidence wins; the conflict is recorded),
  • removes duplicates (near-identical situations within a window),
  • maintains the active context, and
  • builds a Unified Situation it publishes ONLY to the Executive Brain.

The Coordinator is now the only gateway into Executive Intelligence. It reuses the M17
hub's `ConfidenceEngine` and `Timeline` (no rewrite). Never-raises; thread-safe; degrades
gracefully when a brain or service is absent.
"""

from __future__ import annotations

import logging
import threading
import uuid
from difflib import SequenceMatcher
from typing import Optional

from core.perception.hub.confidence import ConfidenceEngine
from core.perception.hub.config import TimelineConfig
from core.perception.hub.timeline import Timeline

from .config import CoordinatorConfig
from .events import CoordinatorEvent
from .unified_situation import UnifiedSituation

log = logging.getLogger("friday.coordinator")


class CognitiveCoordinator:
    def __init__(self, config: Optional[CoordinatorConfig] = None, *, services=None,
                 report_bus=None, executive=None) -> None:
        self.config = config or CoordinatorConfig()
        self.session = self.config.session_id or ("S_" + uuid.uuid4().hex[:8])
        self._services = services
        self._runtime = _svc(services, "runtime")
        self._executive = executive or _svc(services, "executive_brain")
        self._memory = _svc(services, "memory_brain")
        self._confidence = ConfidenceEngine()
        self._timeline = Timeline(TimelineConfig(capacity=self.config.timeline_capacity))
        self._buffer: list = []
        self._context: dict = {"room": "", "activity": "", "situation": ""}
        self._last_published: dict[str, tuple] = {}      # category -> (summary, ts)
        self._lock = threading.Lock()
        self._received = 0
        self._built = 0
        self._published = 0
        self._duplicates = 0
        if report_bus is not None:
            report_bus.subscribe(self.on_report)

    # ── intake ───────────────────────────────────────────────────────────────────
    def on_report(self, report) -> None:
        """Situation Report Bus handler. Buffers the report; coordinates immediately on
        an emergency so urgent situations are never delayed."""
        with self._lock:
            self._buffer.append(report)
            self._received += 1
        self._emit(CoordinatorEvent.REPORT_RECEIVED,
                   {"brain": report.source_brain, "category": report.category})
        if report.category == "emergency" or report.priority >= 0.9:
            self.coordinate()

    def submit(self, report) -> None:
        self.on_report(report)

    # ── coordination cycle ───────────────────────────────────────────────────────
    def coordinate(self) -> list:
        """Process the buffered reports into Unified Situations and publish them to the
        Executive. Returns the unified situations built this cycle. Never raises."""
        if not self.config.enabled:
            return []
        with self._lock:
            reports = self._buffer
            self._buffer = []
        if not reports:
            return []
        try:
            return self._coordinate(reports)
        except Exception as e:  # noqa: BLE001 — a coordinator fault never crashes the core
            log.debug("coordinate failed", exc_info=True)
            return []

    def _coordinate(self, reports: list) -> list:
        out = []
        for group in self._group(reports):
            unified = self._build(group)
            if self._is_duplicate(unified):
                self._duplicates += 1
                self._emit(CoordinatorEvent.DUPLICATE_REMOVED, {"summary": unified.summary})
                continue
            if len(group) > 1:
                self._emit(CoordinatorEvent.REPORTS_MERGED,
                           {"brains": unified.source_brains, "summary": unified.summary})
            if unified.conflicts:
                self._emit(CoordinatorEvent.CONFLICT_RESOLVED, {"conflicts": unified.conflicts})
            self._update_context(group, unified)
            self._timeline.add(unified)
            self._built += 1
            self._emit(CoordinatorEvent.SITUATION_BUILT,
                       {"id": unified.id, "summary": unified.summary,
                        "priority": unified.priority})
            self._publish_to_executive(unified)
            self._remember(unified)
            out.append(unified.to_dict())
        return out

    # ── grouping / merging / conflict ────────────────────────────────────────────
    @staticmethod
    def _group(reports: list) -> list:
        """Emergencies are their own situations; everything else merges into one current
        picture so cross-brain evidence fuses (vision + audio + spatial → one situation)."""
        emergencies = [r for r in reports if r.category == "emergency" or r.priority >= 0.9]
        rest = [r for r in reports if r not in emergencies]
        groups = [[e] for e in emergencies]
        if rest:
            groups.append(rest)
        return groups

    def _build(self, group: list) -> UnifiedSituation:
        conflicts = self._detect_conflicts(group)
        brains = sorted({r.source_brain for r in group})
        conf = self._confidence.combine(
            [r.confidence for r in group],
            agreement=len(brains) > 1 and not conflicts, conflict=bool(conflicts))
        priority = max(r.priority for r in group)
        category = ("emergency" if any(r.category == "emergency" for r in group)
                    else max(group, key=lambda r: r.priority).category)
        ordered = sorted(group, key=lambda r: r.priority, reverse=True)
        headline = ordered[0].summary
        extras = [r.summary for r in ordered[1:] if r.summary != headline]
        summary = headline + (" | " + "; ".join(extras[:3]) if extras else "")
        action = next((r.recommended_action for r in ordered if r.recommended_action), None)
        return UnifiedSituation(
            summary=summary, confidence=conf, priority=priority, category=category,
            source_brains=brains, reports=[r.to_dict() for r in group],
            context=dict(self._context), conflicts=conflicts, recommended_action=action,
            session_id=self.session)

    @staticmethod
    def _detect_conflicts(group: list) -> list:
        """A conflict is two brains asserting mutually-exclusive user states."""
        states = {}
        for r in group:
            s = r.data.get("user_state")
            if s:
                states.setdefault(s, []).append(r.source_brain)
        present = {"present", "at_desk", "working", "walking", "entering_room"}
        if "unavailable" in states and (set(states) & present):
            return [{"type": "presence", "states": list(states.keys()),
                     "resolution": "higher confidence wins"}]
        return []

    # ── dedup / context / publish ────────────────────────────────────────────────
    def _is_duplicate(self, unified: UnifiedSituation) -> bool:
        prev = self._last_published.get(unified.category)
        now = unified.timestamp
        if prev is not None and now - prev[1] < self.config.dedup_window_s:
            if SequenceMatcher(None, prev[0], unified.summary).ratio() >= self.config.dedup_similarity:
                return True
        self._last_published[unified.category] = (unified.summary, now)
        return False

    def _update_context(self, group: list, unified: UnifiedSituation) -> None:
        changed = False
        for r in group:
            room = r.data.get("room")
            if room and room != self._context["room"]:
                self._context["room"] = room
                changed = True
            state = r.data.get("user_state")
            if state and state != self._context["activity"]:
                self._context["activity"] = state
                changed = True
        if unified.recommended_action or unified.category in ("user_state", "emergency"):
            self._context["situation"] = unified.summary
        unified.context = dict(self._context)
        if changed:
            self._emit(CoordinatorEvent.CONTEXT_UPDATED, {"context": dict(self._context)})

    def _publish_to_executive(self, unified: UnifiedSituation) -> None:
        if unified.priority < self.config.min_priority_to_executive:
            return
        if self._executive is not None:
            try:
                self._executive.receive(unified.to_dict())
                self._published += 1
                self._emit(CoordinatorEvent.PUBLISHED_TO_EXECUTIVE,
                           {"id": unified.id, "priority": unified.priority})
            except Exception:  # noqa: BLE001
                log.debug("executive.receive failed", exc_info=True)

    def _remember(self, unified: UnifiedSituation) -> None:
        if self._memory is not None and unified.priority >= 0.4:
            try:
                self._memory.remember_situation(unified.to_dict())
            except Exception:  # noqa: BLE001
                log.debug("memory.remember_situation failed", exc_info=True)

    # ── queries / observability ──────────────────────────────────────────────────
    def context(self) -> dict:
        return dict(self._context)

    def recent(self, limit: int = 20) -> list:
        return [u.to_dict() for u in self._timeline.recently(seconds=3600, limit=limit)]

    def current(self) -> Optional[dict]:
        u = self._timeline.current()
        return u.to_dict() if u is not None else None

    def _emit(self, event: CoordinatorEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.publish(event, data, source="coordinator")
        except Exception:  # noqa: BLE001
            log.debug("emit failed for %s", event, exc_info=True)

    def metrics(self) -> dict:
        return {"received": self._received, "built": self._built, "published": self._published,
                "duplicates": self._duplicates, "buffered": len(self._buffer),
                "timeline": len(self._timeline)}

    def health(self) -> dict:
        return {"status": "ok" if self.config.enabled else "disabled", "session": self.session,
                "executive_attached": self._executive is not None,
                "memory_attached": self._memory is not None, **self.metrics()}


def _svc(services, name):
    if services is None:
        return None
    getter = getattr(services, "try_get", None)
    return getter(name) if callable(getter) else None
