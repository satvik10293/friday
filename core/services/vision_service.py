"""
core/services/vision_service.py — FRIDAY V3 (M16)
VisionService — the decoupled source of visual observations. Spatial cognition consumes
*observations*, never vision internals: this adapter reads the public surface of an
injected M14 `VisionSystem` (its scene-graph objects) — or any object exposing `detect()`
— and converts it to plain spatial-observation dicts. With no vision wired it returns an
empty list (graceful). The observation shape is the stable contract (see
core/spatial/interfaces.py::SpatialObservation).
"""

from __future__ import annotations

import logging

log = logging.getLogger("friday.services.vision")


class VisionService:
    name = "vision"

    def __init__(self, vision=None, *, provider=None) -> None:
        # `vision` = a VisionSystem-like (has .scene_graph / .transport); `provider` = an
        # optional zero-arg callable returning ready-made observation dicts (tests/mocks).
        self._vision = vision
        self._provider = provider

    def detect(self) -> list:
        if self._provider is not None:
            try:
                return list(self._provider())
            except Exception:  # noqa: BLE001
                log.debug("vision provider failed", exc_info=True)
                return []
        if self._vision is None:
            return []
        # direct detect() seam if the backend exposes one
        if hasattr(self._vision, "detect"):
            try:
                return list(self._vision.detect())
            except Exception:  # noqa: BLE001
                log.debug("vision.detect failed", exc_info=True)
                return []
        # otherwise read the public scene-graph objects and normalize
        try:
            scene = self._vision.scene_graph.snapshot()
        except Exception:  # noqa: BLE001
            return []
        out = []
        for s in scene.get("scenes", []):
            cam = s.get("camera_id", "")
            for obj in s.get("objects", []):
                center = obj.get("center", {})
                out.append({
                    "object_class": obj.get("kind", "object"),
                    "label": obj.get("label", obj.get("kind", "object")),
                    "confidence": float(obj.get("attributes", {}).get("identity_score", 0.7)),
                    "position": {"x": center.get("x", 0.0), "y": center.get("y", 0.0)},
                    "bbox": obj.get("bbox_norm"),
                    "camera_id": cam,
                    "track_id": obj.get("object_id"),
                    "stable_id": obj.get("stable_id"),
                    "source": "vision",
                })
        return out

    def cameras(self) -> list:
        if self._vision is None:
            return []
        try:
            return self._vision.transport.cameras()
        except Exception:  # noqa: BLE001
            return []

    def health(self) -> dict:
        return {"status": "ok", "backend": "vision_system" if (self._vision or self._provider)
                else "absent", "cameras": len(self.cameras())}
