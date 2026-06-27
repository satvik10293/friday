"""
core/cognition_core/belief_system.py — FRIDAY 6.0 (M13)
The Belief System. Beliefs are first-class, *evolving* cognitive objects — never
immutable facts. Asserting a belief reinforces, revises, or conflicts with what is
already held; conflicts are resolved by confidence and recency; every change records
evidence and updates `last_verification`. Persistence is delegated to an injected
`BeliefRepository`.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .interfaces import BeliefRepository
from .models import Belief, BeliefStatus, Evidence, now


def _reinforce(prior: float, signal: float) -> float:
    """Asymptotic increase toward 1.0 — repeated corroboration raises confidence with
    diminishing returns."""
    return round(min(1.0, prior + (1.0 - prior) * max(0.0, min(1.0, signal)) * 0.5), 4)


def _weaken(prior: float, signal: float) -> float:
    return round(max(0.0, prior - prior * max(0.0, min(1.0, signal)) * 0.5), 4)


class BeliefSystem:
    def __init__(self, repository: BeliefRepository, *,
                 on_event: Optional[Callable[[str, dict], None]] = None,
                 metrics=None) -> None:
        self._repo = repository
        self._on_event = on_event
        self._metrics = metrics

    # ── assert (reinforce / revise / conflict) ──────────────────────────────────
    def assert_belief(self, subject: str, predicate: str, value: Any, *,
                      confidence: float = 0.6, source: str = "system",
                      evidence: Optional[Evidence] = None) -> Belief:
        t0 = time.perf_counter()
        confidence = max(0.0, min(1.0, confidence))
        existing = self._active(subject, predicate)

        if existing is None:
            belief = Belief(subject=subject, predicate=predicate, value=value,
                            confidence=confidence, source=source,
                            supporting_evidence=[evidence] if evidence else [])
            self._repo.add(belief)
            self._fire("belief.asserted", belief)
            return self._done(belief, t0)

        if existing.value == value:                      # reinforce
            if evidence:
                existing.supporting_evidence.append(evidence)
            existing.confidence = _reinforce(existing.confidence, confidence)
            existing.last_verification = now()
            existing.updated_at = now()
            self._repo.update(existing)
            self._fire("belief.revised", existing)
            return self._done(existing, t0)

        # conflict: same subject+predicate, different value
        new_b = Belief(subject=subject, predicate=predicate, value=value,
                       confidence=confidence, source=source,
                       supporting_evidence=[evidence] if evidence else [])
        if confidence >= existing.confidence:            # newcomer wins
            existing.status = BeliefStatus.SUPERSEDED.value
            existing.contradicting_evidence.append(
                Evidence(source=source, detail=f"superseded by value={value!r}", weight=confidence))
            existing.updated_at = now()
            self._repo.update(existing)
            new_b.contradicting_evidence.append(
                Evidence(source=existing.source, detail=f"prior value={existing.value!r}",
                         weight=existing.confidence))
            self._repo.add(new_b)
            self._fire("belief.conflict", new_b)
            return self._done(new_b, t0)
        else:                                            # incumbent holds, but is challenged
            new_b.status = BeliefStatus.SUPERSEDED.value
            self._repo.add(new_b)
            existing.contradicting_evidence.append(
                Evidence(source=source, detail=f"weaker challenge value={value!r}", weight=confidence))
            existing.confidence = _weaken(existing.confidence, confidence * 0.3)
            existing.updated_at = now()
            self._repo.update(existing)
            self._fire("belief.conflict", existing)
            return self._done(existing, t0)

    # ── explicit revision / retraction / verification ───────────────────────────
    def revise(self, belief_id: str, *, value: Any = None, confidence: Optional[float] = None,
               evidence: Optional[Evidence] = None, supports: bool = True) -> Optional[Belief]:
        b = self._repo.get(belief_id)
        if b is None:
            return None
        if value is not None:
            b.value = value
        if confidence is not None:
            b.confidence = max(0.0, min(1.0, confidence))
        if evidence is not None:
            (b.supporting_evidence if supports else b.contradicting_evidence).append(evidence)
        b.last_verification = now()
        b.updated_at = now()
        self._repo.update(b)
        self._fire("belief.revised", b)
        return b

    def retract(self, belief_id: str) -> bool:
        b = self._repo.get(belief_id)
        if b is None:
            return False
        b.status = BeliefStatus.RETRACTED.value
        b.updated_at = now()
        self._repo.update(b)
        self._fire("belief.retracted", b)
        return True

    def verify(self, belief_id: str, *, confidence: Optional[float] = None) -> Optional[Belief]:
        b = self._repo.get(belief_id)
        if b is None:
            return None
        b.last_verification = now()
        if confidence is not None:
            b.confidence = max(0.0, min(1.0, confidence))
        b.updated_at = now()
        self._repo.update(b)
        return b

    # ── queries ─────────────────────────────────────────────────────────────────
    def get(self, belief_id: str) -> Optional[Belief]:
        return self._repo.get(belief_id)

    def query(self, *, subject: Optional[str] = None, predicate: Optional[str] = None,
              active_only: bool = True) -> list[Belief]:
        status = BeliefStatus.ACTIVE.value if active_only else None
        return self._repo.find(subject=subject, predicate=predicate, status=status)

    def about(self, subject: str) -> list[Belief]:
        return self.query(subject=subject, active_only=True)

    def repoint_subject(self, old_subject: str, new_subject: str) -> int:
        """Move every belief from one entity id to another (used on entity merge)."""
        moved = 0
        for b in self._repo.find(subject=old_subject):
            b.subject = new_subject
            b.updated_at = now()
            self._repo.update(b)
            moved += 1
        return moved

    def counts(self) -> dict:
        return self._repo.counts()

    # ── internals ───────────────────────────────────────────────────────────────
    def _active(self, subject: str, predicate: str) -> Optional[Belief]:
        beliefs = self._repo.find(subject=subject, predicate=predicate,
                                  status=BeliefStatus.ACTIVE.value)
        return beliefs[0] if beliefs else None

    def _fire(self, kind: str, belief: Belief) -> None:
        if self._metrics is not None:
            self._metrics.incr(kind)
        if self._on_event is not None:
            self._on_event(kind, {"belief_id": belief.belief_id, "subject": belief.subject,
                                  "predicate": belief.predicate, "confidence": belief.confidence})

    def _done(self, belief: Belief, t0: float) -> Belief:
        if self._metrics is not None:
            self._metrics.record_belief_latency((time.perf_counter() - t0) * 1000.0)
        return belief
