"""
core/spatial/engine.py — FRIDAY V3 (M16)
The Spatial Cognition engine — the orchestrator that turns a stream of observations into
understanding. Per update it:

  1. resolves each observation's room,
  2. tracks objects to persistent identities (new/moved/lost/returned/removed),
  3. writes the persistent Scene Graph,
  4. infers + diffs spatial relationships,
  5. estimates user state and updates the World Model,
  6. records meaningful spatial memory, and
  7. publishes events on the Runtime bus — all through SERVICES (dependency-injected),
     never importing another subsystem's internals.

Designed for long sessions: incremental updates, periodic pruning, bounded memory,
graceful degradation when a service is absent, and never-raises so a spatial fault can
never crash the Cognitive Core.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from .config import SpatialConfig
from .events import SpatialEvent
from .interfaces import SpatialObservation
from .localization import UserLocalizer
from .memory import SpatialMemory
from .queries import SpatialQueryEngine
from .relationships import RelationshipEngine
from .rooms import RoomModel
from .scene_graph import NodeStatus, SceneGraph
from .tracker import ObjectTracker, TrackState

log = logging.getLogger("friday.spatial.engine")

_TRACK_EVENT = {
    TrackState.NEW: SpatialEvent.OBJECT_DETECTED,
    TrackState.TRACKED: SpatialEvent.OBJECT_TRACKED,
    TrackState.MOVED: SpatialEvent.OBJECT_MOVED,
    TrackState.RETURNED: SpatialEvent.OBJECT_RETURNED,
}
_PRUNE_INTERVAL_S = 30.0


class SpatialEngine:
    def __init__(self, config: Optional[SpatialConfig] = None, *, services=None,
                 scene_graph=None, tracker=None, relationships=None, rooms=None,
                 localizer=None, spatial_memory=None, queries=None) -> None:
        self.config = config or SpatialConfig()
        self.session = self.config.session_id or ("S_" + uuid.uuid4().hex[:8])
        self._services = services

        # services (dependency-injected; each optional + graceful) ------------------
        self._runtime = _svc(services, "runtime")
        self._world = _svc(services, "world_model")
        self._mem_service = _svc(services, "memory")
        self._executive = _svc(services, "executive")
        self._learning = _svc(services, "learning")
        self._emotion = _svc(services, "emotion")
        self._audio = _svc(services, "audio")
        self._vision = _svc(services, "vision")

        # components (DI overrides allowed) -----------------------------------------
        persistent = self.config.memory.persistent
        db = self.config.spatial_db_path()
        self.scene = scene_graph or SceneGraph(path=db, persistent=persistent,
                                               session=self.session)
        self.tracker = tracker or ObjectTracker(self.config.tracker)
        self.relationships = relationships or RelationshipEngine(self.config.relationships)
        self.rooms = rooms or RoomModel(self.config.rooms)
        self.localizer = localizer or UserLocalizer(self.config.localization)
        self.memory = spatial_memory or SpatialMemory(
            path=db, persistent=persistent, memory_service=self._mem_service,
            significance_threshold=self.config.memory.significance_threshold,
            dedup_window_s=self.config.memory.dedup_window_s,
            max_movement_history=self.config.memory.max_movement_history, session=self.session)
        self.queries = queries or SpatialQueryEngine(self.scene, self.memory)

        self._updates = 0
        self._last_prune = time.time()
        self._last_user_room = "unknown"

    # ── main update ──────────────────────────────────────────────────────────────
    def update_scene(self, observations: list, *, camera_id: str = "",
                     room: Optional[str] = None, now: Optional[float] = None) -> dict:
        """Ingest a batch of observations (SpatialObservation or dicts). Never raises."""
        if not self.config.enabled:
            return {"enabled": False}
        now = now if now is not None else time.time()
        try:
            return self._update(observations, camera_id, room, now)
        except Exception as e:  # noqa: BLE001 — spatial faults never crash the core
            log.debug("spatial update failed", exc_info=True)
            return {"error": str(e), "session": self.session}

    def _update(self, observations: list, camera_id: str, room: Optional[str],
                now: float) -> dict:
        obs_list = [o if isinstance(o, SpatialObservation) else SpatialObservation.from_dict(o)
                    for o in observations]
        for o in obs_list:
            o.room = room or self.rooms.room_for(camera_id=o.camera_id or camera_id, observation=o)

        summary = {"detected": 0, "moved": 0, "tracked": 0, "returned": 0,
                   "lost": 0, "removed": 0, "relationships": 0}
        touched_rooms: set = set()

        if self.config.tracking:
            updates, lifecycle = self.tracker.update(obs_list, now=now)
        else:
            updates, lifecycle = [], []

        for u in updates:
            o = u.observation
            if self.config.scene_graph:
                node, _created = self.scene.upsert_object(
                    persistent_id=u.persistent_id, object_class=o.object_class,
                    label=o.label or o.object_class, position={"x": u.center[0], "y": u.center[1]},
                    room=u.room, confidence=o.confidence, bbox=o.bbox, session=self.session)
            else:
                node = None
            touched_rooms.add(u.room)
            self._publish(_TRACK_EVENT.get(u.state, SpatialEvent.OBJECT_TRACKED),
                          {"persistent_id": u.persistent_id, "label": o.label or o.object_class,
                           "room": u.room, "state": u.state,
                           "position": {"x": round(u.center[0], 4), "y": round(u.center[1], 4)}})
            self._remember_track(u, now)
            summary[_bucket(u.state)] = summary.get(_bucket(u.state), 0) + 1
            if self._learning is not None:
                self._learning.record("track", {"pid": u.persistent_id, "state": u.state})

        for ev in lifecycle:
            node = self.scene.by_persistent(ev["persistent_id"])
            if node is not None:
                self.scene.mark_status(
                    node.node_id, NodeStatus.LOST if ev["state"] == TrackState.LOST
                    else NodeStatus.REMOVED)
            self._publish(SpatialEvent.OBJECT_LOST if ev["state"] == TrackState.LOST
                          else SpatialEvent.OBJECT_REMOVED, ev)
            self.memory.record_event(kind=ev["state"], persistent_id=ev["persistent_id"],
                                     label=ev["label"], object_class=ev["object_class"],
                                     room=ev["room"], confidence=0.9, ts=now, significant=True)
            summary[ev["state"]] = summary.get(ev["state"], 0) + 1

        if self.config.relationship_reasoning and self.config.scene_graph:
            summary["relationships"] = self._update_relationships(touched_rooms)

        # localization + world model
        audio_events = self._audio.recent_events() if self._audio is not None else []
        user = self.localizer.estimate(observations=obs_list, audio_events=audio_events, now=now)
        self._update_user(user, now)
        self._update_world_model(updates, now)

        self._publish(SpatialEvent.SCENE_UPDATED, {"summary": summary, "session": self.session})
        log.info("[Spatial] scene updated (+%d detected, %d moved, %d rel)",
                 summary["detected"], summary["moved"], summary["relationships"])
        self._maybe_prune(now)
        self._updates += 1
        summary["user"] = user
        return summary

    # ── relationships ────────────────────────────────────────────────────────────
    def _update_relationships(self, rooms: set) -> int:
        changed = 0
        for room in rooms:
            nodes = self.scene.by_room(room)
            rels = self.relationships.infer(nodes)
            by_source: dict[str, list] = {}
            for r in rels:
                by_source.setdefault(r["source"], []).append(r)
            for node in nodes:
                new_rels = by_source.get(node.node_id, [])
                if self.scene.set_relationships(node.node_id, new_rels):
                    changed += 1
                    self._publish(SpatialEvent.RELATIONSHIP_CHANGED,
                                  {"node": node.node_id, "label": node.label,
                                   "relationships": new_rels})
        return changed

    # ── user / world model ───────────────────────────────────────────────────────
    def _update_user(self, user: dict, now: float) -> None:
        if self._world is not None:
            self._safe(lambda: self._world.observe("user", "primary", state={
                "activity": user["state"], "room": user["room"],
                "present": user["present"], "last_seen": now},
                confidence=user.get("confidence", 0.6)))
        self._publish(SpatialEvent.USER_LOCATED, {"state": user["state"], "room": user["room"],
                                                  "present": user["present"]})
        if user.get("moved"):
            self._publish(SpatialEvent.USER_MOVED, {"state": user["state"], "room": user["room"]})
        if user["room"] != self._last_user_room and user["present"]:
            self._publish(SpatialEvent.ROOM_CHANGED,
                          {"from": self._last_user_room, "to": user["room"]})
            if self._executive is not None:
                self._executive.notify({"type": "spatial", "event": "room_changed",
                                        "room": user["room"], "state": user["state"]})
            self._last_user_room = user["room"]
        if user["state"] in ("entering_room", "leaving_room") and self._emotion is not None:
            self._emotion.nudge({"source": "presence", "state": user["state"]})

    def _update_world_model(self, updates: list, now: float) -> None:
        if self._world is None:
            return
        for u in updates:
            o = u.observation
            self._safe(lambda o=o: self._world.observe("object", o.label or o.object_class, state={
                "room": u.room, "x": round(u.center[0], 4), "y": round(u.center[1], 4),
                "last_seen": now, "persistent_id": u.persistent_id},
                confidence=o.confidence))

    @staticmethod
    def _safe(fn) -> None:
        """Run a service call, isolating its failure — one bad service never aborts the
        rest of the scene update (defense in depth atop the wrappers' own guards)."""
        try:
            fn()
        except Exception:  # noqa: BLE001
            log.debug("spatial service call failed", exc_info=True)

    def _remember_track(self, u, now: float) -> None:
        o = u.observation
        if u.state in (TrackState.MOVED, TrackState.RETURNED, TrackState.NEW):
            self.memory.record_event(
                kind={"new": "detected"}.get(u.state, u.state), persistent_id=u.persistent_id,
                label=o.label or o.object_class, object_class=o.object_class, room=u.room,
                confidence=o.confidence, ts=now)
            self.memory.record_movement(persistent_id=u.persistent_id,
                                        label=o.label or o.object_class, room=u.room,
                                        center=u.center, ts=now)
        else:
            self.memory.record_event(kind="tracked", persistent_id=u.persistent_id,
                                     label=o.label or o.object_class, object_class=o.object_class,
                                     room=u.room, confidence=o.confidence, ts=now)

    # ── poll mode (pull from the vision service) ─────────────────────────────────
    def poll(self, *, camera_id: str = "") -> dict:
        """Pull current observations from the VisionService and update the scene. Returns
        the update summary (or an idle marker)."""
        if self._vision is None:
            return {"polled": False, "reason": "no vision service"}
        detections = self._vision.detect()
        if not detections:
            return {"polled": True, "observations": 0}
        return self.update_scene(detections, camera_id=camera_id)

    # ── persistence ──────────────────────────────────────────────────────────────
    def save(self) -> int:
        n = self.scene.save()
        self._publish(SpatialEvent.SCENE_SAVED, {"nodes": n})
        log.info("[Spatial] scene graph saved (%d nodes)", n)
        return n

    def load(self) -> int:
        n = self.scene.load()
        self._publish(SpatialEvent.SCENE_LOADED, {"nodes": n})
        return n

    # ── internals ────────────────────────────────────────────────────────────────
    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < _PRUNE_INTERVAL_S:
            return
        self._last_prune = now
        removed = self.scene.prune(now=now, forget_after_s=self.config.object_timeout)
        for pid in removed:
            self._publish(SpatialEvent.OBJECT_REMOVED, {"persistent_id": pid, "reason": "pruned"})

    def _publish(self, event: SpatialEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.publish(event, data, source="spatial")
        except Exception:  # noqa: BLE001
            log.debug("publish failed for %s", event, exc_info=True)

    # ── observability ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return {"updates": self._updates, "session": self.session,
                "tracker": self.tracker.metrics(), "scene": self.scene.counts(),
                "memory": self.memory.metrics()}

    def health(self) -> dict:
        return {"status": "ok" if self.config.enabled else "disabled", "session": self.session,
                "scene_graph": self.scene.health(), "memory": self.memory.health(),
                "user": self.localizer.health()}

    def close(self) -> None:
        self.scene.close()
        self.memory.close()


def _svc(services, name):
    if services is None:
        return None
    getter = getattr(services, "try_get", None)
    return getter(name) if callable(getter) else None


def _bucket(state: str) -> str:
    return {TrackState.NEW: "detected", TrackState.MOVED: "moved",
            TrackState.RETURNED: "returned", TrackState.TRACKED: "tracked"}.get(state, "tracked")
