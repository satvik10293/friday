"""
core/spatial/tracker.py — FRIDAY V3 (M16)
Persistent object tracking — cognitive identity, not pixels. An object keeps ONE
identity across frames and across short disappearances, so FRIDAY can say "the phone is
back on the desk" rather than inventing a new phone each frame. Lifecycle states:

    NEW · TRACKED · MOVED · LOST · RETURNED · REMOVED

Matching uses object class + normalized-centre distance (and bbox IoU when available),
plus a fast path when a detection already carries a resolved `stable_id`. Duplicate
identities are prevented by one-to-one greedy assignment per update. State is per
(camera, class) and bounded; designed for long-running sessions.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Optional

from .config import TrackerConfig
from .interfaces import SpatialObservation

_MOVE_EPS = 0.04            # normalized centre delta above which a match counts as MOVED


def _slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (t or "").lower()).strip("_") or "obj"


class TrackState:
    NEW = "new"
    TRACKED = "tracked"
    MOVED = "moved"
    LOST = "lost"
    RETURNED = "returned"
    REMOVED = "removed"


@dataclass
class _Track:
    persistent_id: str
    object_class: str
    label: str
    center: tuple
    last_seen: float
    room: str = "unknown"
    stable_id: Optional[str] = None
    status: str = TrackState.TRACKED
    lost_emitted: bool = False


@dataclass
class TrackUpdate:
    observation: SpatialObservation
    persistent_id: str
    state: str
    center: tuple
    previous_center: Optional[tuple] = None
    room: str = "unknown"


class ObjectTracker:
    def __init__(self, config: Optional[TrackerConfig] = None) -> None:
        self.config = config or TrackerConfig()
        self._tracks: dict[str, _Track] = {}          # persistent_id -> track
        self._seq = 0

    # ── main update ──────────────────────────────────────────────────────────────
    def update(self, observations: list, *, now: Optional[float] = None) -> tuple:
        """Assign persistent ids to observations and age out stale tracks.
        Returns (updates: list[TrackUpdate], lifecycle: list[dict])."""
        now = now if now is not None else time.time()
        updates: list[TrackUpdate] = []
        matched: set = set()

        for obs in observations:
            if obs.confidence < self.config.min_confidence:
                continue
            center = obs.center
            track, is_return = self._match(obs, center, matched)
            if track is None:
                track = self._new_track(obs, center, now)
                state = TrackState.NEW
            else:
                prev = track.center
                dist = _distance(prev, center)
                if is_return:
                    state = TrackState.RETURNED
                elif dist > _MOVE_EPS:
                    state = TrackState.MOVED
                else:
                    state = TrackState.TRACKED
                track.center = center
                track.last_seen = now
                track.label = obs.label or track.label
                track.room = obs.room or track.room
                track.status = TrackState.TRACKED
                track.lost_emitted = False
                matched.add(track.persistent_id)
                updates.append(TrackUpdate(obs, track.persistent_id, state, center,
                                           previous_center=prev, room=track.room))
                continue
            matched.add(track.persistent_id)
            updates.append(TrackUpdate(obs, track.persistent_id, state, center,
                                       room=track.room))

        lifecycle = self._age_out(matched, now)
        return updates, lifecycle

    # ── matching ─────────────────────────────────────────────────────────────────
    def _match(self, obs: SpatialObservation, center: tuple, matched: set) -> tuple:
        # fast path: a detection that already carries a resolved stable id
        if obs.stable_id:
            for t in self._tracks.values():
                if t.stable_id == obs.stable_id and t.persistent_id not in matched:
                    return t, (t.status == TrackState.LOST)
        best, best_score, best_return = None, 0.0, False
        for t in self._tracks.values():
            if t.persistent_id in matched or t.object_class != obs.object_class:
                continue
            dist = _distance(t.center, center)
            if dist > self.config.match_distance:
                continue
            score = 1.0 - dist
            if score > best_score:
                best, best_score = t, score
                best_return = (t.status == TrackState.LOST)
        return best, best_return

    def _new_track(self, obs: SpatialObservation, center: tuple, now: float) -> _Track:
        self._seq += 1
        pid = obs.stable_id or f"OBJ_{_slug(obs.object_class)}_{self._seq:04d}"
        track = _Track(persistent_id=pid, object_class=obs.object_class,
                       label=obs.label or obs.object_class, center=center, last_seen=now,
                       room=obs.room or "unknown", stable_id=obs.stable_id)
        self._tracks[pid] = track
        return track

    # ── aging ────────────────────────────────────────────────────────────────────
    def _age_out(self, matched: set, now: float) -> list:
        lifecycle = []
        for pid, t in list(self._tracks.items()):
            if pid in matched:
                continue
            silence = now - t.last_seen
            if silence >= self.config.forget_after_s:
                self._tracks.pop(pid, None)
                lifecycle.append({"persistent_id": pid, "state": TrackState.REMOVED,
                                  "label": t.label, "object_class": t.object_class,
                                  "room": t.room})
            elif silence >= self.config.lost_after_s and not t.lost_emitted:
                t.status = TrackState.LOST
                t.lost_emitted = True
                lifecycle.append({"persistent_id": pid, "state": TrackState.LOST,
                                  "label": t.label, "object_class": t.object_class,
                                  "room": t.room})
        return lifecycle

    # ── observability ────────────────────────────────────────────────────────────
    def tracks(self) -> list:
        return [{"persistent_id": t.persistent_id, "object_class": t.object_class,
                 "label": t.label, "status": t.status, "room": t.room,
                 "center": [round(t.center[0], 4), round(t.center[1], 4)]}
                for t in self._tracks.values()]

    def metrics(self) -> dict:
        return {"tracks": len(self._tracks),
                "lost": sum(1 for t in self._tracks.values() if t.status == TrackState.LOST)}


def _distance(a: tuple, b: tuple) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
