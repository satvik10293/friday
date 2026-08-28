"""
core/vision/processing/tracking.py — FRIDAY 6.1 (M14)
Object tracking: assigns a persistent per-camera track id to detections across frames
via greedy IoU matching, so the same physical object keeps one identity over time.
Always-available (pure numpy). It consumes the detections produced earlier in the same
frame (object detector and/or motion regions), stamps `track_id` onto them in place,
and reports per-track age/velocity.

Track ids are transport-local temporal identity (TRK_<cam>_<n>); they are NOT entity
ids. The Cognitive Bridge later resolves tracks to permanent ENT_ stable ids — tracking
never reasons or resolves.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .base import BoundingBox, VisionProcessor
from .pipeline import VisionPipeline


@dataclass
class _Track:
    track_id: str
    label: str
    bbox: BoundingBox
    last_center: tuple
    age: int = 1
    misses: int = 0
    last_seen: float = field(default_factory=time.time)
    velocity: tuple = (0.0, 0.0)


class ObjectTracker(VisionProcessor):
    name = "tracking"
    kind = "tracking"
    requires = ()

    def __init__(self, config=None) -> None:
        super().__init__()
        self._iou = float(getattr(config, "track_iou_threshold", 0.3))
        self._max_age = int(getattr(config, "track_max_age", 30))
        self._tracks: dict[str, dict[str, _Track]] = {}   # camera_id → {track_id: _Track}
        self._seq: dict[str, int] = {}

    def analyze(self, frame):
        cam = frame.camera_id
        tracks = self._tracks.setdefault(cam, {})
        # only track detections that carry a bbox (objects / motion regions)
        candidates = [d for d in VisionPipeline.pipeline_detections(frame)
                      if d.bbox is not None and d.kind in ("object", "person", "face")]

        matched_tracks: set[str] = set()
        for det in candidates:
            best_id, best_iou = None, 0.0
            for tid, tr in tracks.items():
                if tid in matched_tracks:
                    continue
                score = det.bbox.iou(tr.bbox)
                if score > best_iou:
                    best_id, best_iou = tid, score
            if best_id is not None and best_iou >= self._iou:
                tr = tracks[best_id]
                cx, cy = det.bbox.center
                tr.velocity = (cx - tr.last_center[0], cy - tr.last_center[1])
                tr.bbox, tr.last_center = det.bbox, (cx, cy)
                tr.age += 1
                tr.misses = 0
                tr.last_seen = time.time()
                tr.label = det.label
                det.track_id = best_id
                matched_tracks.add(best_id)
            else:
                tid = self._new_id(cam)
                tracks[tid] = _Track(track_id=tid, label=det.label, bbox=det.bbox,
                                     last_center=det.bbox.center)
                det.track_id = tid
                matched_tracks.add(tid)

        # age out unmatched tracks
        expired = []
        for tid, tr in tracks.items():
            if tid not in matched_tracks:
                tr.misses += 1
                if tr.misses > self._max_age:
                    expired.append(tid)
        for tid in expired:
            tracks.pop(tid, None)

        active = [{"track_id": t.track_id, "label": t.label, "age": t.age,
                   "velocity": [round(t.velocity[0], 2), round(t.velocity[1], 2)],
                   "bbox": t.bbox.to_dict()}
                  for t in tracks.values() if t.misses == 0]
        return [], {"active_tracks": len(active), "tracks": active,
                    "total_tracks_seen": self._seq.get(cam, 0)}

    def _new_id(self, cam: str) -> str:
        n = self._seq.get(cam, 0) + 1
        self._seq[cam] = n
        return f"TRK_{cam}_{n:04d}"
