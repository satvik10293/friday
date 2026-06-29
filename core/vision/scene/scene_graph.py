"""
core/vision/scene/scene_graph.py — FRIDAY 6.1 (M14)
The Scene Graph: a live, per-camera model of *what is where* and *how things relate*.
It tracks persistent objects (keyed by the tracker's track id, later linked to a
permanent ENT_ stable id by the Cognitive Bridge), and computes spatial relationships
(left_of / right_of / above / below / near / overlapping) between them on demand.

Positions are reported two ways:
  • camera-relative  — normalized (0..1) image coordinates (always available).
  • world-relative   — via an optional per-camera calibration hook; absent a calibration
    it returns the camera-relative point tagged ``frame="camera"`` (a clean hook, not a
    fabricated 3-D guess).

Room mapping is a hook too (inject a mapper camera_id → room). The scene graph holds
state and geometry only — it performs no reasoning and writes nothing to the World
Model. Thread-safe; in-memory (a frame-rate structure, snapshotted to Mission Control).
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..processing.base import Detection


@dataclass
class SceneObject:
    object_id: str                            # tracker track id (scene-local identity)
    camera_id: str
    label: str
    kind: str
    center: tuple                             # normalized (x, y)
    bbox_norm: tuple                          # normalized (x, y, w, h)
    first_seen: float
    last_seen: float
    sightings: int = 1
    stable_id: Optional[str] = None           # permanent ENT_ id (set by the bridge)
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"object_id": self.object_id, "camera_id": self.camera_id,
                "label": self.label, "kind": self.kind,
                "stable_id": self.stable_id,
                "center": {"x": round(self.center[0], 4), "y": round(self.center[1], 4)},
                "bbox_norm": {"x": round(self.bbox_norm[0], 4), "y": round(self.bbox_norm[1], 4),
                              "w": round(self.bbox_norm[2], 4), "h": round(self.bbox_norm[3], 4)},
                "sightings": self.sightings, "first_seen": self.first_seen,
                "last_seen": self.last_seen, "attributes": self.attributes}


class SceneGraph:
    def __init__(self, config=None) -> None:
        self._near = float(getattr(config, "near_fraction", 0.12))
        self._overlap = float(getattr(config, "overlap_relation", 0.15))
        self._forget_after = float(getattr(config, "forget_after_s", 30.0))
        self._objects: dict[str, dict[str, SceneObject]] = {}   # camera → {object_id: obj}
        self._calibration: dict[str, Callable] = {}
        self._room_mapper: Optional[Callable[[str], str]] = None
        self._lock = threading.RLock()
        self._updates = 0

    # ── ingest ───────────────────────────────────────────────────────────────────
    def update(self, camera_id: str, detections: list, width: int, height: int, *,
               timestamp: Optional[float] = None) -> list:
        """Upsert tracked objects from one frame; forget stale ones. Returns the live
        objects for the camera. Only detections that name an object/person with a track
        id and a bbox become scene objects (segments/regions/text do not). `width`/
        `height` are the frame dimensions used to normalize geometry (0..1)."""
        now = timestamp if timestamp is not None else time.time()
        with self._lock:
            cam = self._objects.setdefault(camera_id, {})
            for det in detections:
                if det.bbox is None or det.track_id is None:
                    continue
                if det.kind not in ("object", "person", "face"):
                    continue
                center, bbox_norm = self._geom(det, width, height)
                existing = cam.get(det.track_id)
                if existing is not None:
                    existing.center, existing.bbox_norm = center, bbox_norm
                    existing.label, existing.kind = det.label, _norm_kind(det.kind)
                    existing.last_seen = now
                    existing.sightings += 1
                    if det.attributes.get("identity"):
                        existing.attributes["identity"] = det.attributes["identity"]
                else:
                    cam[det.track_id] = SceneObject(
                        object_id=det.track_id, camera_id=camera_id, label=det.label,
                        kind=_norm_kind(det.kind), center=center, bbox_norm=bbox_norm,
                        first_seen=now, last_seen=now,
                        attributes={k: v for k, v in det.attributes.items()
                                    if k in ("identity", "identity_score", "backend")})
            self._forget(cam, now)
            self._updates += 1
            return list(cam.values())

    def set_stable_id(self, camera_id: str, object_id: str, stable_id: str) -> None:
        with self._lock:
            obj = self._objects.get(camera_id, {}).get(object_id)
            if obj is not None:
                obj.stable_id = stable_id

    # ── relationships ────────────────────────────────────────────────────────────
    def relationships(self, camera_id: str) -> list:
        with self._lock:
            objs = list(self._objects.get(camera_id, {}).values())
        rels: list = []
        for i in range(len(objs)):
            for j in range(i + 1, len(objs)):
                rels.extend(self._relate(objs[i], objs[j]))
        return rels

    def _relate(self, a: SceneObject, b: SceneObject) -> list:
        out: list = []
        dx = b.center[0] - a.center[0]
        dy = b.center[1] - a.center[1]
        dist = math.hypot(dx, dy)
        iou = _iou_norm(a.bbox_norm, b.bbox_norm)
        if iou >= self._overlap:
            out.append(self._rel(a, b, "overlapping", round(iou, 3)))
        if dist <= self._near:
            out.append(self._rel(a, b, "near", round(1.0 - dist, 3)))
        # dominant directional relation (a → b)
        if abs(dx) >= abs(dy):
            out.append(self._rel(a, b, "left_of" if dx > 0 else "right_of", round(abs(dx), 3)))
        else:
            out.append(self._rel(a, b, "above" if dy > 0 else "below", round(abs(dy), 3)))
        return out

    @staticmethod
    def _rel(a: SceneObject, b: SceneObject, kind: str, weight: float) -> dict:
        return {"source": a.object_id, "source_label": a.label,
                "target": b.object_id, "target_label": b.label,
                "relation": kind, "weight": weight}

    # ── positions ────────────────────────────────────────────────────────────────
    def camera_position(self, camera_id: str, object_id: str) -> Optional[dict]:
        with self._lock:
            obj = self._objects.get(camera_id, {}).get(object_id)
        if obj is None:
            return None
        return {"frame": "camera", "x": round(obj.center[0], 4), "y": round(obj.center[1], 4)}

    def world_position(self, camera_id: str, object_id: str) -> Optional[dict]:
        """World-relative position via the camera's calibration hook, if registered."""
        cam_pos = self.camera_position(camera_id, object_id)
        if cam_pos is None:
            return None
        calib = self._calibration.get(camera_id)
        if calib is None:
            return {**cam_pos, "frame": "camera", "calibrated": False}
        try:
            wx, wy, wz = calib(cam_pos["x"], cam_pos["y"])
            return {"frame": "world", "x": wx, "y": wy, "z": wz, "calibrated": True}
        except Exception:  # noqa: BLE001
            return {**cam_pos, "frame": "camera", "calibrated": False}

    def set_calibration(self, camera_id: str, fn: Callable) -> None:
        """Register a (x_norm, y_norm) → (X, Y, Z) world transform for a camera."""
        self._calibration[camera_id] = fn

    def set_room_mapper(self, fn: Callable[[str], str]) -> None:
        self._room_mapper = fn

    def room_for(self, camera_id: str) -> str:
        if self._room_mapper is None:
            return "unknown"
        try:
            return self._room_mapper(camera_id)
        except Exception:  # noqa: BLE001
            return "unknown"

    # ── queries / observability ──────────────────────────────────────────────────
    def objects(self, camera_id: Optional[str] = None) -> list:
        with self._lock:
            if camera_id is not None:
                return [o.to_dict() for o in self._objects.get(camera_id, {}).values()]
            return [o.to_dict() for cam in self._objects.values() for o in cam.values()]

    def snapshot(self) -> dict:
        with self._lock:
            cameras = list(self._objects.keys())
        scenes = []
        for cam in cameras:
            scenes.append({"camera_id": cam, "room": self.room_for(cam),
                           "objects": self.objects(cam),
                           "relationships": self.relationships(cam)})
        return {"cameras": len(cameras), "scenes": scenes,
                "object_count": sum(len(s["objects"]) for s in scenes)}

    def metrics(self) -> dict:
        with self._lock:
            total = sum(len(c) for c in self._objects.values())
        return {"updates": self._updates, "objects": total,
                "cameras": len(self._objects)}

    def health(self) -> dict:
        m = self.metrics()
        return {"status": "ok", **m}

    # ── internals ────────────────────────────────────────────────────────────────
    @staticmethod
    def _geom(det: Detection, width: int, height: int):
        """Normalize a detection's pixel bbox to (center, bbox) in 0..1 coordinates so
        spatial relations are resolution-independent."""
        b = det.bbox
        w = float(width) if width else 1.0
        h = float(height) if height else 1.0
        nx, ny, nw, nh = b.x / w, b.y / h, b.w / w, b.h / h
        return (nx + nw / 2.0, ny + nh / 2.0), (nx, ny, nw, nh)

    def _forget(self, cam: dict, now: float) -> None:
        stale = [oid for oid, o in cam.items() if now - o.last_seen > self._forget_after]
        for oid in stale:
            cam.pop(oid, None)


def _norm_kind(kind: str) -> str:
    return "person" if kind in ("person", "face") else kind


def _iou_norm(a: tuple, b: tuple) -> float:
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0
