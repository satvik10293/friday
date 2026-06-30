"""
core/perception/hub/hub.py — FRIDAY V3 (M17)
The Perception Hub — the unified multimodal gateway. Instead of vision, audio, and
spatial each writing memory separately, every sensor publishes observations and the Hub
fuses them into ONE unified cognitive event, reasons about it, updates the active context
and timeline, forwards understanding to the World Model, and remembers only meaningful,
non-duplicate events.

Pipeline (per ingest/perceive cycle):
    modality observations → FUSE → CONFIDENCE gate (+enrich) → REASON → CONTEXT update →
    TIMELINE → World Model (gateway) → Memory (dedup/compress) → events

All collaborators are dependency-injected services; the Hub imports no subsystem's
internals. Thread-safe, never-raises, graceful when services are absent.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

from .config import PerceptionHubConfig
from .confidence import ConfidenceEngine
from .context import ContextEngine
from .events import HubEvent
from .fusion import MultimodalFusion
from .observations import ModalityObservation, UnifiedObservation
from .reasoning import CognitiveReasoner
from .timeline import Timeline

log = logging.getLogger("friday.perception.hub")
_COMPRESS_WINDOW_S = 30.0          # identical situations within this window are compressed


class PerceptionHub:
    def __init__(self, config: Optional[PerceptionHubConfig] = None, *, services=None,
                 fusion=None, confidence=None, reasoner=None, context=None, timeline=None) -> None:
        self.config = config or PerceptionHubConfig()
        self.session = self.config.session_id or ("S_" + uuid.uuid4().hex[:8])
        self._services = services
        self._runtime = _svc(services, "runtime")
        self._world = _svc(services, "world_model")
        self._memory = _svc(services, "memory")
        self._executive = _svc(services, "executive")
        self._learning = _svc(services, "learning")
        self._vision = _svc(services, "vision")
        self._audio = _svc(services, "audio")
        self._spatial = _svc(services, "spatial")

        self.confidence = confidence or ConfidenceEngine(self.config.confidence_cfg)
        self.fusion = fusion or MultimodalFusion(self.config.fusion_cfg, self.confidence)
        self.context = context or ContextEngine()
        self.timeline = timeline or Timeline(self.config.timeline_cfg)
        self.reasoner = reasoner or CognitiveReasoner()

        self._lock = threading.Lock()
        self._last_sig: dict[str, tuple] = {}          # subject -> (signature, ts) for compression
        self._cycles = 0
        self._created = 0
        self._rejected = 0

    # ── ingest (push) ────────────────────────────────────────────────────────────
    def ingest(self, observations: list, *, session_id: str = "") -> dict:
        """Fuse + process a batch of modality observations into unified events.
        Never raises."""
        if not self.config.enabled:
            return {"enabled": False}
        try:
            return self._ingest(observations, session_id or self.session)
        except Exception as e:  # noqa: BLE001 — a perception fault never crashes the core
            log.debug("perception ingest failed", exc_info=True)
            return {"error": str(e), "session": self.session}

    def _ingest(self, observations: list, session_id: str) -> dict:
        unified_list = (self.fusion.fuse(observations, session_id=session_id)
                        if self.config.fusion else
                        [self._wrap(o, session_id) for o in observations])
        results = []
        for u in unified_list:
            results.append(self._process(u))
        self._cycles += 1
        self._publish(HubEvent.PERCEPTION_READY,
                      {"observations": len(results), "session": session_id})
        return {"observations": len(results), "accepted": sum(1 for r in results if r.get("accepted")),
                "results": results, "situation": self.context.snapshot().get("situation", "")}

    def _process(self, u: UnifiedObservation) -> dict:
        u.previous_context = self.context.snapshot()

        # confidence gate (+ enrichment before rejecting)
        if self.config.confidence_engine and u.confidence < self.config.minimum_confidence:
            self._enrich(u)
            if u.confidence < self.config.minimum_confidence:
                self._rejected += 1
                self._publish(HubEvent.OBSERVATION_REJECTED,
                              {"id": u.id, "confidence": u.confidence, "location": u.location})
                return {"id": u.id, "accepted": False, "reason": "low_confidence",
                        "confidence": u.confidence}

        # reasoning
        if self.config.reasoning:
            conclusions = self.reasoner.reason(u, self.context.snapshot())
            if conclusions:
                u.conclusions = conclusions
                u.event_category = conclusions[0]["category"]
                u.importance = max(u.importance, conclusions[0]["confidence"])
                self._publish(HubEvent.REASONING_COMPLETED,
                              {"id": u.id, "conclusions": conclusions})

        # context
        ctx_res = self.context.update(u)
        if ctx_res["changed"]:
            self._publish(HubEvent.CONTEXT_CHANGED, {"context": ctx_res["context"]})
        if ctx_res["situation_changed"]:
            self._publish(HubEvent.SITUATION_CHANGED, {"situation": ctx_res["context"]["situation"]})
            self._notify_executive(u, ctx_res["context"])

        # timeline
        if self.config.timeline:
            self.timeline.add(u)
            self._publish(HubEvent.TIMELINE_UPDATED, {"id": u.id, "size": len(self.timeline)})

        # world model (the Hub is the gateway) + memory
        self._to_world_model(u)
        if self.config.store_unified_events:
            self._remember(u)
        if self._learning is not None:
            self._learning.record("unified_observation", {"category": u.event_category,
                                                          "confidence": u.confidence})

        self._created += 1
        self._publish(HubEvent.OBSERVATION_MERGED if len(u.source_modules) > 1
                      else HubEvent.OBSERVATION_CREATED,
                      {"id": u.id, "category": u.event_category, "location": u.location,
                       "confidence": u.confidence, "sources": u.source_modules})
        log.info("[Perception] unified observation (%s @ %s, conf %.2f)",
                 u.event_category, u.location or "?", u.confidence)
        return {"id": u.id, "accepted": True, "category": u.event_category,
                "location": u.location, "confidence": u.confidence, "conclusions": u.conclusions}

    # ── perceive (pull from services) ────────────────────────────────────────────
    def perceive(self) -> dict:
        """Collect current observations from the sensor services and process them."""
        return self.ingest(self._collect())

    def _collect(self) -> list:
        obs: list = []
        room = self.context.snapshot().get("room", "")
        if self._vision is not None:
            for d in _safe_call(self._vision.detect, []):
                obs.append(ModalityObservation(
                    source="vision", category="object", label=d.get("label", "object"),
                    confidence=float(d.get("confidence", 0.7)), location=d.get("room", room),
                    objects=[d.get("label")] if d.get("label") else [],
                    people=["user"] if d.get("object_class") == "person" else []))
        if self._audio is not None:
            for e in _safe_call(lambda: self._audio.recent_events(limit=10), []):
                obs.append(ModalityObservation(
                    source="audio", category="sound", label=e.get("sound", "sound"),
                    confidence=float(e.get("confidence", 0.6)), location=room,
                    data={"category": e.get("category")}))
        if self._spatial is not None:
            snap = _safe_call(self._spatial.snapshot, {})
            user = (snap or {}).get("user", {})
            if user:
                obs.append(ModalityObservation(
                    source="spatial", category="user_state",
                    label=user.get("last_state", "present"), confidence=0.8,
                    location=user.get("room", room),
                    data={"user_state": user.get("last_state")}))
        return obs

    # ── enrichment / world model / memory ────────────────────────────────────────
    def _enrich(self, u: UnifiedObservation) -> None:
        """Try to raise a borderline observation's confidence from corroborating context
        (same room + overlapping objects) before rejecting it."""
        ctx = u.previous_context
        if ctx.get("room") and ctx["room"] == u.location and \
                set(ctx.get("objects", [])) & set(u.related_objects):
            u.confidence = self.confidence.combine([u.confidence, 0.5], agreement=True)

    def _to_world_model(self, u: UnifiedObservation) -> None:
        if self._world is None:
            return
        name = f"{u.event_category}@{u.location or 'unknown'}"
        _safe_call(lambda: self._world.observe("situation", name, state={
            "objects": u.related_objects, "people": u.related_people,
            "situation": u.conclusions[0]["situation"] if u.conclusions else "",
            "audio": u.audio_context, "confidence": u.confidence, "ts": u.timestamp},
            confidence=u.confidence), None)

    def _remember(self, u: UnifiedObservation) -> None:
        if self._memory is None:
            return
        if u.importance < 0.4 and not u.conclusions:
            return                                      # not meaningful enough
        subject, sig, now = u.subject(), u.signature(), time.time()
        with self._lock:
            prev = self._last_sig.get(subject)
            if prev is not None and prev[0] == sig and now - prev[1] < _COMPRESS_WINDOW_S:
                return                                  # compress repetitive identical event
            self._last_sig[subject] = (sig, now)
        text = u.conclusions[0]["situation"] if u.conclusions else \
            f"{u.event_category} in {u.location or 'the environment'}" + \
            (f" involving {', '.join(u.related_objects[:3])}" if u.related_objects else "")
        _safe_call(lambda: self._memory.remember(text, kind="perception",
                   metadata={"id": u.id, "category": u.event_category, "confidence": u.confidence}),
                   None)

    def _notify_executive(self, u: UnifiedObservation, context: dict) -> None:
        if self._executive is None:
            return
        _safe_call(lambda: self._executive.notify({
            "type": "perception", "situation": context.get("situation", ""),
            "room": u.location, "objects": u.related_objects, "importance": u.importance,
            "category": u.event_category}), None)

    @staticmethod
    def _wrap(o, session_id: str) -> UnifiedObservation:
        mo = o if isinstance(o, ModalityObservation) else ModalityObservation.from_dict(o)
        return UnifiedObservation(timestamp=mo.timestamp, session_id=session_id,
                                  source_modules=[mo.source], confidence=mo.confidence,
                                  location=mo.location, related_objects=mo.objects,
                                  related_people=mo.people, event_category=mo.category,
                                  sources=[mo.to_dict()])

    # ── understanding for the Executive ──────────────────────────────────────────
    def situation(self) -> dict:
        ctx = self.context.snapshot()
        current = self.timeline.current()
        return {"situation": ctx.get("situation", ""), "room": ctx.get("room", ""),
                "activity": ctx.get("activity", ""), "objects": ctx.get("objects", []),
                "people": ctx.get("people", []),
                "current_observation": current.to_dict() if current is not None else None,
                "important_changes": [u.to_dict() for u in self.timeline.recently(limit=5)
                                      if u.importance >= 0.6]}

    # ── internals / observability ────────────────────────────────────────────────
    def _publish(self, event: HubEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.publish(event, data, source="perception")
        except Exception:  # noqa: BLE001
            log.debug("publish failed for %s", event, exc_info=True)

    def metrics(self) -> dict:
        return {"cycles": self._cycles, "created": self._created, "rejected": self._rejected,
                "session": self.session, "context": self.context.metrics(),
                "timeline": self.timeline.metrics(), "reasoner": self.reasoner.metrics()}

    def health(self) -> dict:
        return {"status": "ok" if self.config.enabled else "disabled", "session": self.session,
                "context": self.context.health(), "timeline": self.timeline.health(),
                "created": self._created, "rejected": self._rejected}


def _svc(services, name):
    if services is None:
        return None
    getter = getattr(services, "try_get", None)
    return getter(name) if callable(getter) else None


def _safe_call(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        log.debug("perception service call failed", exc_info=True)
        return default
