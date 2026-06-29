"""
core/vision/transport/service.py — FRIDAY 6.1 (M14)
The Vision Transport facade: the single object the rest of FRIDAY uses to bring
cameras online and pull Frame objects. Wires the Camera Manager (with its registry,
decoder, metrics) and exposes camera registration helpers, the consume API for the
next stage, the Flask/SocketIO server, Mission Control data, and runtime attachment.

Transport only — it produces Frames; it never builds observations or touches the
World Model. Side-effect-free to import.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from .adapters.array_adapter import ArrayAdapter
from .adapters.browser_adapter import BrowserAdapter
from .adapters.webcam_adapter import RtspAdapter, WebcamAdapter
from .decoder import FrameDecoder
from .frame import Frame
from .frame_queue import OverflowPolicy
from .manager import CameraManager
from .registry import CameraRegistry

log = logging.getLogger("friday.vision")

_MANIFEST_PATH = Path(__file__).resolve().parent / "architecture.json"


class VisionTransport:
    def __init__(self, *, runtime=None, persistent_registry: bool = False,
                 registry_path: Optional[str] = None, decoder: Optional[FrameDecoder] = None,
                 queue_size: int = 2, target_fps: float = 10.0,
                 overflow: OverflowPolicy = OverflowPolicy.DROP_OLDEST) -> None:
        registry = CameraRegistry(registry_path, persistent=persistent_registry)
        self.manager = CameraManager(decoder=decoder, registry=registry, runtime=runtime,
                                     queue_size=queue_size, target_fps=target_fps,
                                     overflow=overflow)
        self._runtime = runtime

    # ── bring cameras online (one helper per camera family) ─────────────────────
    def connect_browser(self, token: str, *, label: str = "") -> str:
        return self.manager.register(BrowserAdapter(key=token, label=label))

    def add_webcam(self, source=0, *, label: str = "") -> str:
        return self.manager.register(WebcamAdapter(key=f"usb:{source}", source=source, label=label))

    def add_rtsp(self, url: str, *, label: str = "") -> str:
        return self.manager.register(RtspAdapter(key=f"rtsp:{url}", url=url, label=label))

    def add_array_camera(self, key: str, frames, *, loop: bool = False, label: str = "") -> str:
        return self.manager.register(ArrayAdapter(key=key, frames=frames, loop=loop, label=label))

    def register(self, adapter) -> str:
        return self.manager.register(adapter)

    def remove(self, camera_id: str) -> bool:
        return self.manager.remove(camera_id)

    # ── ingest + consume ────────────────────────────────────────────────────────
    def submit_raw(self, camera_id: str, payload, **kw) -> bool:
        return self.manager.submit_raw(camera_id, payload, **kw)

    def pump(self, camera_id: str, **kw) -> int:
        return self.manager.pump_camera(camera_id, **kw)

    def consume(self, camera_id: str) -> Optional[Frame]:
        """The next pipeline stage (Vision Processing → Observation Builder) pulls
        Frame objects from here."""
        return self.manager.consume(camera_id)

    def latest(self, camera_id: str) -> Optional[Frame]:
        return self.manager.latest(camera_id)

    def cameras(self) -> list[dict]:
        return [c.to_dict() for c in self.manager.list()]

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def start(self) -> None:
        self.manager.start()

    def stop(self) -> None:
        self.manager.stop()

    def server(self, **kw):
        from .server import VisionTransportServer
        return VisionTransportServer(self.manager, **kw)

    # ── observability ───────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        return self.manager.dashboard()

    def health(self) -> dict:
        return self.manager.health()

    def metrics(self) -> dict:
        return self.manager.metrics.snapshot()

    def manifest(self) -> dict:
        try:
            return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def attach(self, runtime) -> None:
        self._runtime = runtime
        self.manager.attach(runtime)

    def close(self) -> None:
        self.manager.close()


_transport: Optional[VisionTransport] = None
_lock = threading.Lock()


def get_vision_transport(**kw) -> VisionTransport:
    global _transport
    with _lock:
        if _transport is None:
            _transport = VisionTransport(**kw)
    return _transport
