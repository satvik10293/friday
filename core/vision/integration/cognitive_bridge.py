"""
core/vision/integration/cognitive_bridge.py — FRIDAY 6.1 (M14)
The Cognitive Bridge. This is where visual perception enters cognition — and the place
the architecture's hardest invariant is enforced: *vision never bypasses the pipeline*.

For each frame's Observations the bridge:
  1. updates the Scene Graph (persistent objects + spatial relationships),
  2. ingests every Observation through the M6 Perception Manager, whose ResolvingWorldFeed
     resolves a permanent ENT_ stable id and writes the World Model — the SAME sanctioned
     path used by every other sensor (vision does not write the World Model directly),
  3. links scene objects to their stable ids (via the M13 Entity Linker / resolver),
  4. records significant observations, sightings, and visual events in Visual Memory,
  5. ranks observations through the M5 Attention System,
  6. emits cognition-stage vision events on the runtime bus.

Every collaborator is injected and optional; with none wired the bridge degrades to a
no-op that still updates the scene graph. The bridge performs NO reasoning of its own —
it routes evidence to the subsystems that do.
"""

from __future__ import annotations

import logging
from typing import Optional

from .events import VisionCognitionEvent

log = logging.getLogger("friday.vision.bridge")

_SCENE_CHANGE_THRESHOLD = 0.15      # mean normalized luminance-signature delta


class CognitiveBridge:
    def __init__(self, *, perception=None, cognition=None, attention=None,
                 scene_graph=None, visual_memory=None, runtime=None, config=None) -> None:
        self._perception = perception          # core.perception PerceptionManager
        self._cognition = cognition            # core.cognition_core CognitionCore
        self._attention = attention            # core.attention AttentionSystem
        self._scene = scene_graph
        self._memory = visual_memory
        self._runtime = runtime
        self._linker = cognition.linker() if cognition is not None else None
        self._last_signature: dict[str, list] = {}
        self._motion_state: dict[str, bool] = {}
        self._metrics = {"ingested": 0, "promoted": 0, "linked": 0,
                         "events": 0, "scene_changes": 0}

    # ── main entry ───────────────────────────────────────────────────────────────
    def process(self, result, observations: list, frame=None) -> dict:
        """Route one frame's Observations into cognition. `result` is the
        ProcessingResult (geometry + signature); `observations` come from the
        Observation Builder; `frame` supplies dimensions + evidence."""
        cam = result.camera_id
        out = {"camera_id": cam, "ingested": 0, "promoted": 0, "linked": 0,
               "events": [], "stable_ids": {}}

        # 1) scene graph — persistent objects + spatial structure
        if self._scene is not None and frame is not None:
            try:
                self._scene.update(cam, result.detections(), frame.width, frame.height,
                                   timestamp=result.timestamp)
            except Exception:  # noqa: BLE001
                log.debug("scene graph update failed", exc_info=True)

        # 2/3/4) per-observation ingest → resolve → link → remember
        for obs in observations:
            summary = bool(obs.metadata.get("summary"))
            status, significance, promoted = self._ingest(obs)
            out["ingested"] += 1
            self._metrics["ingested"] += 1
            if promoted:
                out["promoted"] += 1
                self._metrics["promoted"] += 1

            if not summary:
                sid = self._link(obs, cam, out)
                self._remember_object(obs, cam, sid, significance)
                if status == "received":
                    self._event(VisionCognitionEvent.OBJECT_APPEARED, cam, out,
                                {"subject": obs.subject(),
                                 "label": obs.payload.get("label")})
                if promoted:
                    self._event(VisionCognitionEvent.OBJECT_PROMOTED, cam, out,
                                {"subject": obs.subject(), "stable_id": sid})
            else:
                self._remember_summary(obs, significance)
                self._scene_dynamics(obs, cam, out)

        # 5) attention ranking (focus signal; non-fatal, advisory)
        self._rank(observations)
        return out

    # ── steps ────────────────────────────────────────────────────────────────────
    def _ingest(self, obs):
        """Ingest through the Perception Manager (the no-bypass path). Returns
        (status, significance, promoted)."""
        if self._perception is None:
            return "received", float(obs.confidence), False
        try:
            res = self._perception.ingest(obs)
            return res.get("status", "received"), float(res.get("significance", 0.0)), \
                bool(res.get("promoted"))
        except Exception:  # noqa: BLE001 — a cognition failure must never crash vision
            log.debug("perception ingest failed", exc_info=True)
            return "received", float(obs.confidence), False

    def _link(self, obs, cam: str, out: dict) -> Optional[str]:
        """Resolve the observation's entity to a permanent stable id and link the scene
        object to it. Idempotent (the resolver dedups + reinforces)."""
        if self._linker is None:
            return None
        kind = obs.metadata.get("entity_kind", "object")
        name = obs.metadata.get("entity_name") or obs.payload.get("name")
        if not name:
            return None
        try:
            sid = self._linker.link(kind, str(name), confidence=float(obs.confidence))
        except Exception:  # noqa: BLE001
            log.debug("entity link failed", exc_info=True)
            return None
        track_id = obs.metadata.get("track_id")
        if track_id and self._scene is not None:
            self._scene.set_stable_id(cam, track_id, sid)
            out["stable_ids"][track_id] = sid
        out["linked"] += 1
        self._metrics["linked"] += 1
        self._event(VisionCognitionEvent.ENTITY_LINKED, cam, out,
                    {"stable_id": sid, "track_id": track_id, "name": name}, count_only=True)
        return sid

    def _remember_object(self, obs, cam: str, sid: Optional[str], significance: float) -> None:
        if self._memory is None:
            return
        try:
            self._memory.remember_observation(obs, significance)
            center = obs.payload.get("spatial", {}).get("center_norm", {})
            self._memory.record_sighting(
                stable_id=sid, track_id=obs.metadata.get("track_id"), camera_id=cam,
                label=obs.payload.get("label", ""),
                center=(center.get("x", 0.0), center.get("y", 0.0)),
                ts=obs.timestamp, data={"confidence": obs.confidence})
        except Exception:  # noqa: BLE001
            log.debug("visual memory write failed", exc_info=True)

    def _remember_summary(self, obs, significance: float) -> None:
        if self._memory is None:
            return
        try:
            self._memory.remember_observation(obs, significance)
        except Exception:  # noqa: BLE001
            log.debug("visual memory summary write failed", exc_info=True)

    def _scene_dynamics(self, obs, cam: str, out: dict) -> None:
        """Motion start/stop + scene-change detection from the frame summary."""
        payload = obs.payload
        # motion edges
        motion = bool(payload.get("motion"))
        prev_motion = self._motion_state.get(cam, False)
        if motion != prev_motion:
            self._motion_state[cam] = motion
            evt = VisionCognitionEvent.MOTION_STARTED if motion else VisionCognitionEvent.MOTION_STOPPED
            self._event(evt, cam, out, {"motion_score": payload.get("motion_score")})
            if self._memory is not None:
                try:
                    self._memory.record_event(cam, evt.value, subject=obs.subject(),
                                              data={"motion_score": payload.get("motion_score")},
                                              ts=obs.timestamp)
                except Exception:  # noqa: BLE001
                    log.debug("event write failed", exc_info=True)
        # scene change from the luminance signature
        sig = payload.get("scene_signature") or []
        prev = self._last_signature.get(cam)
        self._last_signature[cam] = sig
        if prev and sig and len(prev) == len(sig):
            magnitude = sum(abs(a - b) for a, b in zip(prev, sig)) / (255.0 * len(sig))
            if magnitude >= _SCENE_CHANGE_THRESHOLD:
                self._metrics["scene_changes"] += 1
                self._event(VisionCognitionEvent.SCENE_CHANGED, cam, out,
                            {"magnitude": round(magnitude, 4)})
                if self._memory is not None:
                    try:
                        self._memory.record_scene_change(cam, magnitude,
                                                         data={"object_count": payload.get("object_count")},
                                                         ts=obs.timestamp)
                    except Exception:  # noqa: BLE001
                        log.debug("scene change write failed", exc_info=True)

    def _rank(self, observations: list) -> None:
        if self._attention is None or not observations:
            return
        try:
            self._attention.rank_observations([o.attention_dict() for o in observations])
        except Exception:  # noqa: BLE001
            log.debug("attention ranking failed", exc_info=True)

    # ── events ───────────────────────────────────────────────────────────────────
    def _event(self, event: VisionCognitionEvent, cam: str, out: dict, data: dict,
               *, count_only: bool = False) -> None:
        self._metrics["events"] += 1
        if not count_only:
            out["events"].append({"event": event.value, "camera_id": cam, **data})
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data={"camera_id": cam, **data}, source="vision")
        except Exception:  # noqa: BLE001
            log.debug("event emit failed", exc_info=True)

    # ── observability ────────────────────────────────────────────────────────────
    def metrics(self) -> dict:
        return dict(self._metrics)

    def health(self) -> dict:
        return {"status": "ok",
                "perception": self._perception is not None,
                "cognition": self._cognition is not None,
                "attention": self._attention is not None,
                "scene_graph": self._scene is not None,
                "visual_memory": self._memory is not None,
                **self._metrics}
