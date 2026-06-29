"""
core/vision/service.py — FRIDAY 6.1 (M14)
The Vision System facade: the single object the rest of FRIDAY uses for visual
perception. It composes the full M14 pipeline —

  Transport → Camera Manager → Frame → Processing Pipeline → Observation Builder →
  Cognitive Bridge (Attention → Perception → Entity Resolver → World Model) →
  Scene Graph + Visual Memory

— behind one dependency-injected seam, and drives processing on its OWN thread so the
transport/socket threads are never blocked by AI work. Cameras come online through the
transport helpers; a processing loop consumes decoded Frames and turns each into
Observations that improve the World Model.

Everything is observable (dashboard/health/metrics/manifest) and resilient: a failure
anywhere in processing is logged and isolated — the Cognitive Core never crashes
because of vision. Side-effect-free to import; nothing starts until `start()`.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

from .config import VisionConfig
from .integration.cognitive_bridge import CognitiveBridge
from .observation.builder import ObservationBuilder
from .processing.pipeline import VisionPipeline
from .processing.registry import default_registry
from .scene.scene_graph import SceneGraph
from .memory.visual_memory import VisualMemory
from .transport.frame_queue import OverflowPolicy
from .transport.service import VisionTransport

log = logging.getLogger("friday.vision.system")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class VisionSystem:
    def __init__(self, *, config: Optional[VisionConfig] = None, runtime=None,
                 perception=None, cognition=None, attention=None, world_model=None,
                 transport: Optional[VisionTransport] = None) -> None:
        self.config = config or VisionConfig()
        self._runtime = runtime

        # transport (reuse the productionized M14-part-1 layer) ---------------------
        if transport is not None:
            self.transport = transport
        else:
            tc = self.config.transport
            self.transport = VisionTransport(
                runtime=runtime, persistent_registry=tc.persistent_registry,
                registry_path=tc.registry_path, queue_size=tc.queue_size,
                target_fps=tc.target_fps, overflow=OverflowPolicy(tc.overflow))

        # processing -----------------------------------------------------------------
        registry = default_registry(self.config.processing)
        processors = [p for p in (registry.create(n) for n in self.config.processing.enabled)
                      if p is not None]
        self.pipeline = VisionPipeline(processors)
        self.builder = ObservationBuilder(self.config.observation)
        self.scene_graph = SceneGraph(self.config.scene)
        mc = self.config.memory
        self.visual_memory = VisualMemory(
            self.config.visual_memory_path() if mc.persistent else None,
            persistent=mc.persistent, significance_threshold=mc.significance_threshold,
            max_object_history=mc.max_object_history)

        # cognition — build a perception manager over the resolving feed if cognition
        # + world model are present and no perception manager was injected -----------
        if perception is None and cognition is not None and world_model is not None:
            perception = self._build_perception(cognition, world_model, attention)
        self.bridge = CognitiveBridge(
            perception=perception, cognition=cognition, attention=attention,
            scene_graph=self.scene_graph, visual_memory=self.visual_memory,
            runtime=runtime, config=self.config)

        # processing loop ------------------------------------------------------------
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._frames_processed = 0
        self._errors = 0
        self._last_process_at: dict[str, float] = {}
        self._warnings: list = []

    # ── camera registration (delegates to transport) ─────────────────────────────
    def connect_browser(self, token: str, *, label: str = "") -> str:
        return self.transport.connect_browser(token, label=label)

    def add_webcam(self, source=0, *, label: str = "") -> str:
        return self.transport.add_webcam(source, label=label)

    def add_rtsp(self, url: str, *, label: str = "") -> str:
        return self.transport.add_rtsp(url, label=label)

    def add_array_camera(self, key: str, frames, *, loop: bool = False, label: str = "") -> str:
        return self.transport.add_array_camera(key, frames, loop=loop, label=label)

    def register(self, adapter) -> str:
        return self.transport.register(adapter)

    def remove(self, camera_id: str) -> bool:
        return self.transport.remove(camera_id)

    def submit_raw(self, camera_id: str, payload, **kw) -> bool:
        return self.transport.submit_raw(camera_id, payload, **kw)

    def server(self, **kw):
        return self.transport.server(**kw)

    # ── processing ───────────────────────────────────────────────────────────────
    def process_camera(self, camera_id: str) -> dict:
        """Consume one decoded Frame for a camera and run the full perception pipeline.
        Returns a per-frame summary. Never raises — vision failures are isolated."""
        try:
            frame = self.transport.consume(camera_id)
            if frame is None:
                # The VisionSystem is the sole frame driver: pull one frame on demand
                # (decode for push adapters / capture for pull adapters). This runs on
                # the processing thread — off all transport/socket threads — and keeps
                # finite/array cameras lossless and processing deterministic.
                self.transport.pump(camera_id, max_frames=1)
                frame = self.transport.consume(camera_id)
        except Exception:  # noqa: BLE001
            return {"camera_id": camera_id, "frame": False, "error": "consume failed"}
        if frame is None:
            return {"camera_id": camera_id, "frame": False}
        try:
            result = self.pipeline.process(frame)
            observations = self.builder.build(result, frame)
            bridge_out = self.bridge.process(result, observations, frame)
            self._frames_processed += 1
            return {"camera_id": camera_id, "frame": True, "frame_id": frame.frame_id,
                    "detections": len(result.detections()),
                    "observations": len(observations), "total_ms": round(result.total_ms, 3),
                    "promoted": bridge_out["promoted"], "events": bridge_out["events"]}
        except Exception as e:  # noqa: BLE001
            self._errors += 1
            self._warn(f"processing error on {camera_id}: {e}")
            log.debug("vision processing failed", exc_info=True)
            return {"camera_id": camera_id, "frame": True, "error": str(e)}

    def process_all(self) -> list:
        return [self.process_camera(cid) for cid in self.transport.manager.camera_ids()]

    def warmup(self) -> None:
        """Pre-load processor backends off the hot path."""
        self.pipeline.warmup()

    # ── lifecycle ────────────────────────────────────────────────────────────────
    def start(self, *, warmup: bool = False) -> "VisionSystem":
        # Start only the transport health heartbeat — NOT the per-camera capture
        # workers. The VisionSystem's processing loop is the sole frame driver
        # (pump-on-demand in process_camera), so running capture workers too would
        # double-read pull adapters.
        self.transport.manager.start_heartbeat()
        if warmup:
            self.warmup()
        self._stop.clear()
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._process_loop, daemon=True,
                                            name="friday-vision-processing")
            self._worker.start()
        return self

    def _process_loop(self) -> None:  # pragma: no cover - timing/thread loop
        """Single dedicated processing thread (off all transport threads). Round-robins
        cameras, throttled to processing fps so it never starves the host or the
        transport workers."""
        min_interval = 1.0 / max(0.1, self.config.processing.max_processing_fps)
        while not self._stop.is_set():
            ran = False
            for cid in self.transport.manager.camera_ids():
                now = time.time()
                if now - self._last_process_at.get(cid, 0.0) < min_interval:
                    continue
                self._last_process_at[cid] = now
                res = self.process_camera(cid)
                ran = ran or res.get("frame", False)
            time.sleep(min_interval if not ran else min_interval * 0.25)

    def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self.transport.stop()

    def close(self) -> None:
        self.stop()
        try:
            self.transport.close()
        except Exception:  # noqa: BLE001
            pass
        self.visual_memory.close()

    # ── observability ────────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return {
            "title": "Vision System", "milestone": "M14",
            "transport": self.transport.dashboard(),
            "pipeline": self.pipeline.metrics(),
            "observations": self.builder.metrics(),
            "scene": self.scene_graph.snapshot(),
            "scene_metrics": self.scene_graph.metrics(),
            "visual_memory": self.visual_memory.metrics(),
            "bridge": self.bridge.metrics(),
            "processing": {"frames_processed": self._frames_processed,
                           "errors": self._errors, "warnings": self._warnings[-10:]},
        }

    def metrics(self) -> dict:
        return {"frames_processed": self._frames_processed, "errors": self._errors,
                "pipeline": self.pipeline.metrics(),
                "bridge": self.bridge.metrics(),
                "transport": self.transport.metrics(),
                "scene": self.scene_graph.metrics(),
                "visual_memory": self.visual_memory.metrics()}

    def health(self) -> dict:
        t = self.transport.health()
        status = "ok"
        if t.get("status") == "degraded" or self._errors:
            status = "degraded"
        return {"status": status, "transport": t,
                "pipeline": self.pipeline.health(),
                "scene_graph": self.scene_graph.health(),
                "visual_memory": self.visual_memory.health(),
                "bridge": self.bridge.health(),
                "frames_processed": self._frames_processed, "errors": self._errors}

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        self._runtime = runtime
        self.transport.attach(runtime)
        try:
            runtime.register_health("vision", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)

    # ── internals ────────────────────────────────────────────────────────────────
    def _build_perception(self, cognition, world_model, attention):
        from core.perception.manager import PerceptionManager
        feed = cognition.resolving_world_feed(world_model)
        return PerceptionManager(world_feed=feed, attention=attention, runtime=self._runtime)

    def _warn(self, message: str) -> None:
        self._warnings.append({"ts": time.time(), "message": message})
        if len(self._warnings) > 100:
            self._warnings = self._warnings[-100:]


# ── singleton ──────────────────────────────────────────────────────────────────────
_system: Optional[VisionSystem] = None
_lock = threading.Lock()


def get_vision_system(**kw) -> VisionSystem:
    global _system
    with _lock:
        if _system is None:
            _system = VisionSystem(**kw)
    return _system
