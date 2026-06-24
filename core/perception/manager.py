"""
core/perception/manager.py — FRIDAY 4.0 (M6)
The Perception Manager. The brain of the perception layer: it ingests raw
observations and decides what they *mean*.

Responsibilities:
  • Deduplicate observations (same subject + same values → a merge, not a new fact)
  • Merge repeated observations (track an occurrence count + last-seen)
  • Track observation history (append-only, per subject)
  • Compute observation significance (novelty · confidence · impact · goal-relevance)
  • Promote important observations into the M5 World Model (via WorldFeed)
  • Archive low-value observations

It also bridges to the M5 Attention System so attention can focus on observations.
Every dependency is injected and optional; the manager degrades gracefully.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from .events import PerceptionEvent
from .health import aggregate
from .models import Observation, ObservationConfidence
from .store import PerceptionStore

log = logging.getLogger("friday.perception.manager")


class PerceptionManager:
    def __init__(self, store: Optional[PerceptionStore] = None, world_feed=None,
                 attention=None, goal_service=None, runtime=None,
                 promote_confidence: float = 0.7, promote_significance: float = 0.6,
                 archive_significance: float = 0.15, repeat_threshold: int = 3) -> None:
        self._store = store if store is not None else PerceptionStore()
        self._world = world_feed
        self._attention = attention
        self._goals = goal_service
        self._runtime = runtime
        self._promote_conf = promote_confidence
        self._promote_sig = promote_significance
        self._archive_sig = archive_significance
        self._repeat_threshold = repeat_threshold
        self._seen: dict[str, dict] = {}
        self._metrics: dict[str, int] = defaultdict(int)

    # ── ingest ─────────────────────────────────────────────────────────────────
    def ingest(self, obs: Observation) -> dict:
        subject = obs.subject()
        prev = self._seen.get(subject)
        sig = self.significance(obs, prev)

        if prev is None:
            status, count = "received", 1
        else:
            count = prev["count"] + 1
            status = "ignored" if obs.value_signature() == prev["sig"] else "changed"

        self._seen[subject] = {"sig": obs.value_signature(), "count": count,
                               "last_seen": obs.timestamp, "confidence": obs.confidence}
        self._store.upsert_observation(obs, significance=sig, status=status, count=count,
                                       last_seen=obs.timestamp)
        self._store.add_history(subject, status,
                                {"confidence": obs.confidence, "significance": sig})
        self._metrics["ingested"] += 1
        self._metrics[status] += 1
        self._emit({"received": PerceptionEvent.RECEIVED, "changed": PerceptionEvent.CHANGED,
                    "ignored": PerceptionEvent.IGNORED}[status], obs, subject)

        result = {"status": status, "significance": round(sig, 4), "subject": subject,
                  "count": count, "promoted": False, "archived": False, "observation": obs}

        if self._should_promote(obs, sig, count):
            self.promote(obs)
            result["promoted"] = True
        elif status == "ignored" and sig <= self._archive_sig:
            self.archive(obs)
            result["archived"] = True
        return result

    def ingest_batch(self, observations) -> list[dict]:
        return [self.ingest(o) for o in observations]

    # ── significance ───────────────────────────────────────────────────────────
    def significance(self, obs: Observation, prev: Optional[dict] = None) -> float:
        if prev is None:
            novelty = 1.0
        elif obs.value_signature() != prev.get("sig"):
            novelty = 0.7                       # changed → still notable
        else:
            novelty = 0.2                       # same as before → routine
        confidence = ObservationConfidence.clamp(obs.confidence)
        impact = ObservationConfidence.clamp(obs.metadata.get("impact", 0.5))
        goal_rel = self._goal_relevance(obs)
        return ObservationConfidence.clamp(
            0.30 * novelty + 0.30 * confidence + 0.20 * impact + 0.20 * goal_rel)

    # ── promotion / archival ───────────────────────────────────────────────────
    def _should_promote(self, obs: Observation, significance: float, count: int) -> bool:
        high_conf = obs.confidence >= self._promote_conf
        high_sig = significance >= self._promote_sig
        repeated = count >= self._repeat_threshold
        goal_relevant = self._goal_relevance(obs) >= 0.5
        return high_conf and (high_sig or repeated or goal_relevant)

    def promote(self, obs: Observation) -> Optional[object]:
        entity = self._world.observe(obs) if self._world is not None else None
        self._store.set_status(obs.id, "promoted")
        self._store.add_history(obs.subject(), "promoted", {"confidence": obs.confidence})
        self._metrics["promoted"] += 1
        self._emit(PerceptionEvent.PROMOTED, obs, obs.subject())
        return entity

    def archive(self, obs: Observation) -> None:
        self._store.set_status(obs.id, "archived")
        self._store.add_history(obs.subject(), "archived", {})
        self._metrics["archived"] += 1
        self._emit(PerceptionEvent.ARCHIVED, obs, obs.subject())

    # ── attention bridge (M5) ──────────────────────────────────────────────────
    def focus(self, limit: int = 5) -> list:
        """Rank recent observations by salience via the M5 Attention System."""
        if self._attention is None:
            return []
        rows = self._store.recent(limit * 3)
        obs_dicts = [{
            "id": r["id"], "name": r["subject"], "ts": r["ts"],
            "importance": r["confidence"],
            "urgency": (r["metadata"] or {}).get("impact", 0.5),
            "priority": r["significance"],
        } for r in rows]
        return self._attention.rank_observations(obs_dicts)[:limit]

    # ── queries ────────────────────────────────────────────────────────────────
    def recent(self, limit: int = 50, status: Optional[str] = None) -> list[dict]:
        return self._store.recent(limit, status=status)

    def history(self, subject: str, limit: int = 50) -> list[dict]:
        return self._store.history(subject, limit)

    def promoted(self, limit: int = 20) -> list[dict]:
        return self._store.recent(limit, status="promoted")

    # ── diagnostics ────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        s = dict(self._metrics)
        s["store"] = self._store.counts()
        return s

    def health(self, sensor_health: Optional[dict] = None) -> dict:
        return aggregate(dict(self._metrics), sensor_health or {})

    # ── internals ──────────────────────────────────────────────────────────────
    def _goal_relevance(self, obs: Observation) -> float:
        if self._goals is None:
            return 0.0
        try:
            goals = self._goals.list_goals()
        except Exception:
            return 0.0
        if not goals:
            return 0.0
        text = (obs.subject() + " " + " ".join(str(v) for v in obs.payload.values())).lower()
        for g in goals:
            words = [w for w in str(getattr(g, "title", "")).lower().split() if len(w) > 3]
            if any(w in text for w in words):
                return 0.8
        return 0.0

    def _emit(self, event: PerceptionEvent, obs: Observation, subject: str) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data={"subject": subject, "type": obs.type.value,
                                            "confidence": obs.confidence,
                                            "observation_id": obs.id}, source="perception")
        except Exception:
            log.debug("perception event emit failed", exc_info=True)
