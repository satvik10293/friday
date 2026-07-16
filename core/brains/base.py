"""
core/brains/base.py — FRIDAY V3 (M17 revision)
The Cognitive Brain framework. FRIDAY is no longer independent modules; it is a society
of specialized Cognitive Brains. Every brain owns local reasoning, local state, local
memory, and situation reporting, and follows one standard lifecycle:

    observe() → analyze() → update_local_memory() → reason() →
    generate_situation_report() → publish() → wait()

No raw sensor data leaves a brain — only structured `SituationReport`s, published on the
`SituationReportBus`. The Cognitive Coordinator consumes those reports; the Executive
Brain never sees raw observations. Brains import no other brain's internals — they reach
peers (and underlying subsystems) only through services.

Pure stdlib, thread-safe, never-raises: one brain failing never stops the others.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.nervous.reflexes import reflex as _reflex   # @reflex marker (M50)

log = logging.getLogger("friday.brains")


# ── Situation Report ────────────────────────────────────────────────────────────────
def new_report_id() -> str:
    return "SR_" + uuid.uuid4().hex[:12]


@dataclass
class SituationReport:
    """The only thing a Cognitive Brain emits — processed knowledge, never raw data."""
    source_brain: str
    summary: str
    confidence: float = 0.5
    priority: float = 0.5
    category: str = "status"
    evidence: list = field(default_factory=list)           # supporting evidence (dicts)
    local_memory_summary: dict = field(default_factory=dict)
    recommended_action: Optional[str] = None
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    report_id: str = field(default_factory=new_report_id)

    def subject(self) -> str:
        return f"{self.source_brain}:{self.category}"

    def to_dict(self) -> dict:
        return {"report_id": self.report_id, "source_brain": self.source_brain,
                "timestamp": self.timestamp, "summary": self.summary,
                "confidence": round(float(self.confidence), 4),
                "priority": round(float(self.priority), 4), "category": self.category,
                "evidence": self.evidence, "local_memory_summary": self.local_memory_summary,
                "recommended_action": self.recommended_action, "data": self.data}


class SituationReportBus:
    """Thread-safe pub/sub for Situation Reports — the Situation Report Bus. Brains
    publish; the Coordinator (and observers) subscribe. Bounded history for replay."""

    def __init__(self, *, history: int = 1000) -> None:
        self._subs: list[Callable[[SituationReport], None]] = []
        self._history: deque = deque(maxlen=history)
        self._lock = threading.Lock()
        self._published = 0

    def subscribe(self, handler: Callable[[SituationReport], None]) -> None:
        with self._lock:
            self._subs.append(handler)

    def publish(self, report: SituationReport) -> None:
        with self._lock:
            handlers = list(self._subs)
            self._history.append(report)
            self._published += 1
        for h in handlers:
            try:
                h(report)
            except Exception:  # noqa: BLE001 — a bad subscriber never breaks publishing
                log.debug("SR subscriber failed", exc_info=True)

    def recent(self, limit: int = 50, *, source: Optional[str] = None) -> list:
        with self._lock:
            items = list(self._history)
        if source:
            items = [r for r in items if r.source_brain == source]
        return [r.to_dict() for r in items[-limit:][::-1]]

    def stats(self) -> dict:
        return {"published": self._published, "subscribers": len(self._subs)}


# ── Local Memory ────────────────────────────────────────────────────────────────────
class LocalMemory:
    """A brain's private working store: named bounded caches + a small key/value area.
    Private to its owning brain — never shared directly (peers see only reports)."""

    def __init__(self) -> None:
        self._caches: dict[str, deque] = {}
        self._kv: dict[str, Any] = {}
        self._lock = threading.RLock()

    def cache(self, name: str, *, capacity: int = 128) -> None:
        with self._lock:
            if name not in self._caches:
                self._caches[name] = deque(maxlen=capacity)

    def push(self, name: str, item: Any, *, capacity: int = 128) -> None:
        with self._lock:
            if name not in self._caches:
                self._caches[name] = deque(maxlen=capacity)
            self._caches[name].append(item)

    def items(self, name: str) -> list:
        with self._lock:
            return list(self._caches.get(name, []))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._kv[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._kv.get(key, default)

    def summary(self) -> dict:
        with self._lock:
            return {"caches": {k: len(v) for k, v in self._caches.items()},
                    "state": dict(self._kv)}


# ── Cognitive Brain ─────────────────────────────────────────────────────────────────
class CognitiveBrain:
    """Base class for every Cognitive Brain. Subclasses implement the lifecycle hooks;
    `tick()` runs one full, never-raises cognitive cycle and returns the report (or None
    when there is nothing worth reporting)."""

    name: str = "brain"

    def __init__(self, *, services=None, config: Optional[dict] = None,
                 report_bus: Optional[SituationReportBus] = None) -> None:
        self.services = services
        self.config = dict(config or {})
        self.local = LocalMemory()
        self._bus = report_bus
        self._ticks = 0
        self._reports = 0
        self._errors = 0
        self._last_tick_ok = True
        self._service_attrs: set = set()      # attrs holding service handles (recover)
        self._last_report: Optional[SituationReport] = None

    # ── lifecycle hooks (override) ───────────────────────────────────────────────
    def observe(self) -> Any:
        """Pull raw input from this brain's own service(s). Returns brain-specific data."""
        return None

    def analyze(self, observation: Any) -> Any:
        return observation

    def update_local_memory(self, analysis: Any) -> None:
        """Default: no-op. Brains override to maintain their private caches."""

    def reason(self, analysis: Any) -> Any:
        return analysis

    def generate_situation_report(self, insight: Any) -> Optional[SituationReport]:
        return None

    def wait(self) -> None:
        """Loop-pacing hook (the brain service handles real scheduling)."""

    # ── one cognitive cycle (never raises) ───────────────────────────────────────
    def tick(self) -> Optional[SituationReport]:
        self._ticks += 1
        try:
            observation = self.observe()
            analysis = self.analyze(observation)
            self.update_local_memory(analysis)
            insight = self.reason(analysis)
            report = self.generate_situation_report(insight)
        except Exception:  # noqa: BLE001 — a brain fault never stops the society
            self._errors += 1
            self._last_tick_ok = False
            log.debug("brain %s tick failed", self.name, exc_info=True)
            return None
        self._last_tick_ok = True
        if report is not None:
            self._last_report = report
            self._reports += 1
            self.publish(report)
        return report

    def publish(self, report: SituationReport) -> None:
        if self._bus is not None:
            self._bus.publish(report)

    def set_bus(self, bus: SituationReportBus) -> None:
        self._bus = bus

    # ── helpers ──────────────────────────────────────────────────────────────────
    def _service(self, name: str):
        if self.services is None:
            return None
        getter = getattr(self.services, "try_get", None)
        return getter(name) if callable(getter) else None

    def _resolve(self, attr: str, name: str):
        """Resolve-and-cache a service, retrying while unresolved. Brains built
        before their service registers must not stay blind forever — a one-shot
        lookup in __init__ did exactly that."""
        svc = getattr(self, attr, None)
        if svc is None:
            svc = self._service(name)
            if svc is not None:
                setattr(self, attr, svc)
        # remember which attrs hold service handles, so recover() can drop them
        self._service_attrs.add(attr)
        return svc

    @_reflex
    def recover(self):
        """The nervous system's reflex (M50) for a wedged brain: drop cached
        service handles so they re-resolve fresh, and clear the transient
        error latch so the next tick re-evaluates honestly. Safe + idempotent —
        it re-reads state, never destroys any. (@reflex: fired autonomously.)"""
        for attr in list(self._service_attrs):
            setattr(self, attr, None)
        self._last_tick_ok = True
        return "recovered"

    def _report(self, summary: str, *, confidence: float = 0.6, priority: float = 0.5,
                category: str = "status", evidence: Optional[list] = None,
                recommended_action: Optional[str] = None, data: Optional[dict] = None
                ) -> SituationReport:
        return SituationReport(
            source_brain=self.name, summary=summary, confidence=confidence, priority=priority,
            category=category, evidence=evidence or [], recommended_action=recommended_action,
            data=data or {}, local_memory_summary=self.local.summary())

    # ── observability ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"brain": self.name, "ticks": self._ticks, "reports": self._reports,
                "errors": self._errors}

    def health(self) -> dict:
        # honest health: a brain whose last cycle failed is degraded, not "ok"
        return {"status": "ok" if self._last_tick_ok else "degraded",
                "brain": self.name, "errors": self._errors,
                "last_report": self._last_report.summary if self._last_report else None}

    # ── public service surface (one per brain) ───────────────────────────────────
    def service(self) -> "CognitiveBrain":
        """Each brain exposes itself as its one public service."""
        return self
