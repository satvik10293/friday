"""
core/vision/mission_control.py — FRIDAY 6.1 (M14)
Mission Control integration for the Vision System. Assembles the cockpit's vision panel
from the live system so everything the operator needs is observable: connected cameras,
per-camera FPS / latency / queue depth / dropped frames / health, plus pipeline object
count / detection rate / processing time, thread status, errors, and warnings. Includes
an optional on-demand live-preview (base64 JPEG of the latest frame) — computed only when
asked, never streamed into the dashboard payload.

Read-only: it observes the system, it does not drive it.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

log = logging.getLogger("friday.vision.mission_control")


class VisionPanel:
    def __init__(self, system) -> None:
        self._system = system

    # ── panel ────────────────────────────────────────────────────────────────────
    def panel(self) -> dict:
        sys = self._system
        if sys is None:
            return {"status": "absent", "cameras": []}
        try:
            transport = sys.transport.dashboard()
            pipeline = sys.pipeline.metrics()
            scene = sys.scene_graph.snapshot()
            bridge = sys.bridge.metrics()
            mem = sys.visual_memory.metrics()
            health = sys.health()
            cameras = [self._camera_panel(c) for c in transport.get("cameras", [])]
            tmetrics = transport.get("transport", {})
            return {
                "status": health.get("status", "ok"),
                "render": "vision",
                "cameras": cameras,
                "camera_count": len(cameras),
                "transport": {
                    "total_fps": tmetrics.get("total_fps", 0.0),
                    "frames_received": tmetrics.get("frames_received", 0),
                    "frames_dropped": tmetrics.get("frames_dropped", 0),
                    "frames_corrupt": tmetrics.get("frames_corrupt", 0),
                    "drop_rate": tmetrics.get("drop_rate", 0.0),
                    "reconnects": tmetrics.get("reconnects", 0),
                },
                "pipeline": {
                    "frames_processed": pipeline.get("frames_processed", 0),
                    "avg_processing_ms": pipeline.get("avg_total_ms", 0.0),
                    "processors": pipeline.get("processors", []),
                },
                "perception": {
                    "object_count": scene.get("object_count", 0),
                    "observations_ingested": bridge.get("ingested", 0),
                    "promoted": bridge.get("promoted", 0),
                    "entities_linked": bridge.get("linked", 0),
                    "events": bridge.get("events", 0),
                    "scene_changes": bridge.get("scene_changes", 0),
                    "detection_rate": self._detection_rate(pipeline, scene),
                },
                "scene": scene,
                "visual_memory": mem,
                "threads": self._threads(),
                "errors": health.get("errors", 0),
                "warnings": sys.dashboard().get("processing", {}).get("warnings", []),
            }
        except Exception as e:  # noqa: BLE001 — a panel must never break the cockpit
            log.debug("vision panel build failed", exc_info=True)
            return {"status": "degraded", "error": str(e), "cameras": []}

    def _camera_panel(self, cam: dict) -> dict:
        health = cam.get("health", {})
        queue = cam.get("queue", {})
        return {
            "camera_id": cam.get("camera_id"),
            "kind": cam.get("kind"), "label": cam.get("label"),
            "status": cam.get("status"),
            "fps": health.get("fps", 0.0),
            "latency_ms": health.get("avg_latency_ms", 0.0),
            "bandwidth_bps": health.get("bandwidth_bps", 0.0),
            "queue_depth": queue.get("depth", 0),
            "dropped": health.get("dropped", 0),
            "quality": health.get("quality"),
            "health_score": health.get("health_score", 0),
            "reconnects": cam.get("reconnects", 0),
        }

    def _threads(self) -> dict:
        sys = self._system
        worker = getattr(sys, "_worker", None)
        return {"processing_thread_alive": bool(worker and worker.is_alive()),
                "transport_cameras": len(sys.transport.manager.camera_ids())}

    @staticmethod
    def _detection_rate(pipeline: dict, scene: dict) -> float:
        frames = pipeline.get("frames_processed", 0)
        return round(scene.get("object_count", 0) / frames, 4) if frames else 0.0

    # ── live preview (on demand only) ────────────────────────────────────────────
    def preview(self, camera_id: str, *, quality: int = 50) -> Optional[str]:
        """Return a base64 data-URL JPEG of the camera's latest frame, or None. Computed
        only when explicitly requested by the cockpit — never part of the panel payload."""
        sys = self._system
        frame = sys.transport.latest(camera_id)
        if frame is None or frame.data is None:
            return None
        try:
            from .transport.decoder import FrameDecoder
            jpeg = FrameDecoder().encode_jpeg(frame.data, quality=quality)
            if not jpeg:
                return None
            return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")
        except Exception:  # noqa: BLE001
            return None
