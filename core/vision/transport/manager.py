"""
core/vision/transport/manager.py — FRIDAY 6.1 (M14)
The Camera Manager — the single point through which every camera is reached. No
subsystem ever touches a transport socket directly; everything goes through here.

Responsibilities: registration / removal / lookup, permanent camera ids, connection
lifecycle, frame ingest into per-camera bounded queues, health monitoring, failure
recovery (reconnect detection), statistics, and event publication. It performs NO
cognition — it moves frames and reports health, nothing more.

Frame flow:
  pull adapter.read()  ─┐
                        ├─►  _ingest(camera_id, frame)  ─►  per-camera FrameQueue
  push adapter.read() ──┘     (health + metrics + events)      ▲ consumed by next stage
  (push frames arrive via submit_raw → adapter buffer → read on a worker thread)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

from .adapters.base import CameraAdapter, PushAdapter
from .camera import CameraInfo, CameraStatus
from .decoder import FrameDecoder
from .events import VisionEvent
from .frame import Frame
from .frame_queue import FrameQueue, OverflowPolicy
from .health import CameraHealth
from .metrics import TransportMetrics
from .registry import CameraRegistry

log = logging.getLogger("friday.vision.manager")


@dataclass
class _Record:
    adapter: CameraAdapter
    info: CameraInfo
    queue: FrameQueue
    health: CameraHealth
    worker: Optional[threading.Thread] = None
    last_dropped: int = 0


class CameraManager:
    def __init__(self, *, decoder: Optional[FrameDecoder] = None,
                 registry: Optional[CameraRegistry] = None, runtime=None,
                 metrics: Optional[TransportMetrics] = None,
                 queue_size: int = 2, target_fps: float = 10.0,
                 overflow: OverflowPolicy = OverflowPolicy.DROP_OLDEST) -> None:
        self._decoder = decoder if decoder is not None else FrameDecoder()
        self._registry = registry if registry is not None else CameraRegistry()
        self._runtime = runtime
        self.metrics = metrics if metrics is not None else TransportMetrics()
        self._queue_size = queue_size
        self._target_fps = target_fps
        self._overflow = overflow
        self._records: dict[str, _Record] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._heartbeat: Optional[threading.Thread] = None

    # ── registration / lifecycle ────────────────────────────────────────────────
    def register(self, adapter: CameraAdapter, *, target_fps: Optional[float] = None) -> str:
        """Register (or reconnect) a camera. Returns its permanent id. Re-registering
        the same key (e.g. a browser refresh) reuses the id and counts a reconnect."""
        cid = self._registry.allocate(adapter.key, kind=adapter.kind.value, label=adapter.label)
        adapter.camera_id = cid
        if isinstance(adapter, PushAdapter) and adapter._decoder is None:
            adapter.set_decoder(self._decoder)
        with self._lock:
            existing = self._records.get(cid)
            if existing is not None:                      # reconnect
                existing.adapter = adapter
                existing.info.status = CameraStatus.CONNECTED.value
                existing.info.reconnects += 1
                self.metrics.reconnect()
                adapter.open()
                self._emit(VisionEvent.CAMERA_RECOVERED, {"camera_id": cid,
                           "reconnects": existing.info.reconnects})
                return cid
            info = CameraInfo(camera_id=cid, kind=adapter.kind.value, label=adapter.label,
                              key=adapter.key, status=CameraStatus.CONNECTED.value,
                              metadata=adapter.info_metadata())
            rec = _Record(adapter=adapter,
                          info=info,
                          queue=FrameQueue(self._queue_size, policy=self._overflow),
                          health=CameraHealth(cid, target_fps=target_fps or self._target_fps))
            self._records[cid] = rec
        adapter.open()
        self.metrics.camera_registered()
        self._emit(VisionEvent.CAMERA_REGISTERED, {"camera_id": cid, "kind": adapter.kind.value,
                   "label": adapter.label})
        return cid

    def remove(self, camera_id: str) -> bool:
        with self._lock:
            rec = self._records.pop(camera_id, None)
        if rec is None:
            return False
        try:
            rec.adapter.close()
        except Exception:  # noqa: BLE001
            pass
        rec.info.status = CameraStatus.REMOVED.value
        self.metrics.camera_removed()
        self._emit(VisionEvent.CAMERA_REMOVED, {"camera_id": camera_id})
        return True

    def get(self, camera_id: str) -> Optional[CameraInfo]:
        rec = self._records.get(camera_id)
        return rec.info if rec else None

    def list(self) -> list[CameraInfo]:
        with self._lock:
            return [r.info for r in self._records.values()]

    def camera_ids(self) -> list[str]:
        return list(self._records.keys())

    # ── ingest (push producers call submit_raw; the manager pumps frames) ────────
    def submit_raw(self, camera_id: str, payload, *, capture_time: float = 0.0,
                   recv_time: Optional[float] = None) -> bool:
        """Entry point for push cameras (e.g. the SocketIO handler). Fast: buffers the
        raw payload on the adapter; decoding happens on a worker thread."""
        rec = self._records.get(camera_id)
        if rec is None or not isinstance(rec.adapter, PushAdapter):
            self._emit(VisionEvent.TRANSPORT_WARNING,
                       {"camera_id": camera_id, "reason": "submit to unknown/non-push camera"})
            return False
        rec.adapter.submit(payload, capture_time=capture_time, recv_time=recv_time)
        return True

    def pump_camera(self, camera_id: str, *, max_frames: Optional[int] = None) -> int:
        """Drain available frames from a camera's adapter into its queue (synchronous;
        the per-camera worker thread loops this). Returns frames ingested."""
        rec = self._records.get(camera_id)
        if rec is None:
            return 0
        n = 0
        while max_frames is None or n < max_frames:
            frame = rec.adapter.read()
            if frame is None:
                break
            self._ingest(rec, frame)
            n += 1
        return n

    def _ingest(self, rec: _Record, frame: Frame) -> None:
        if frame.flags.corrupt:
            self.metrics.frame_corrupt()
            self._emit(VisionEvent.FRAME_CORRUPT, {"camera_id": rec.info.camera_id})
            return
        rec.queue.put(frame)
        drops = rec.queue.dropped - rec.last_dropped
        if drops > 0:
            for _ in range(drops):
                rec.health.on_drop()
                self.metrics.frame_dropped()
            rec.last_dropped = rec.queue.dropped
            self._emit(VisionEvent.FRAME_DROPPED, {"camera_id": rec.info.camera_id, "dropped": drops})
        rec.health.on_frame(latency_ms=frame.latency_ms, nbytes=frame.nbytes())
        rec.health.set_queue_depth(rec.queue.depth)
        self.metrics.frame_received(frame.nbytes())

        prev = rec.info.status
        rec.info.last_frame_at = frame.timestamp
        new = rec.health.status()
        rec.info.status = new
        if prev in (CameraStatus.DEGRADED.value, CameraStatus.DISCONNECTED.value,
                    CameraStatus.CONNECTED.value, CameraStatus.REGISTERED.value) \
                and new == CameraStatus.STREAMING.value:
            self._emit(VisionEvent.CAMERA_STREAMING, {"camera_id": rec.info.camera_id})

    # ── consume (the next stage pulls Frame objects from here) ───────────────────
    def consume(self, camera_id: str) -> Optional[Frame]:
        rec = self._records.get(camera_id)
        return rec.queue.get() if rec else None

    def latest(self, camera_id: str) -> Optional[Frame]:
        rec = self._records.get(camera_id)
        return rec.queue.peek() if rec else None

    # ── threads ─────────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Start a worker thread per camera + the heartbeat monitor. Never restarts
        the cameras themselves."""
        self._stop.clear()
        with self._lock:
            for rec in self._records.values():
                self._ensure_worker(rec)
        self.start_heartbeat()

    def start_heartbeat(self) -> None:
        """Start only the health/recovery heartbeat (no per-camera capture workers).
        Used when an upstream driver — e.g. the VisionSystem processing loop — pulls
        frames itself via pump_camera(), so the manager must not also run capture
        workers (that would double-read pull adapters)."""
        self._stop.clear()
        if self._heartbeat is None or not self._heartbeat.is_alive():
            self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True,
                                               name="friday-vision-heartbeat")
            self._heartbeat.start()

    def _ensure_worker(self, rec: _Record) -> None:  # pragma: no cover - threads
        if rec.worker and rec.worker.is_alive():
            return
        rec.worker = threading.Thread(target=self._worker_loop, args=(rec,), daemon=True,
                                      name=f"friday-vision-{rec.info.camera_id}")
        rec.worker.start()

    def _worker_loop(self, rec: _Record) -> None:  # pragma: no cover - threads
        idle = 1.0 / max(1.0, rec.adapter.target_fps * 2)
        while not self._stop.is_set():
            try:
                frame = rec.adapter.read()
            except Exception:  # noqa: BLE001 — a faulty adapter must not crash transport
                log.debug("adapter read error", exc_info=True)
                frame = None
            if frame is None:
                time.sleep(idle)
                continue
            self._ingest(rec, frame)

    def _heartbeat_loop(self) -> None:  # pragma: no cover - threads
        while not self._stop.is_set():
            self.check_health()
            time.sleep(1.0)

    def check_health(self) -> None:
        """Detect degraded/disconnected cameras (synchronous; the heartbeat loops it)."""
        now = time.time()
        with self._lock:
            records = list(self._records.values())
        for rec in records:
            status = rec.health.status(now)
            if status != rec.info.status and rec.info.status not in (
                    CameraStatus.REMOVED.value, CameraStatus.STREAMING.value):
                pass
            if status == CameraStatus.DEGRADED.value and rec.info.status != CameraStatus.DEGRADED.value:
                rec.info.status = status
                self._emit(VisionEvent.CAMERA_DEGRADED, {"camera_id": rec.info.camera_id})
            elif status == CameraStatus.DISCONNECTED.value and \
                    rec.info.status != CameraStatus.DISCONNECTED.value:
                rec.info.status = status
                self._emit(VisionEvent.CAMERA_DISCONNECTED, {"camera_id": rec.info.camera_id})

    def stop(self) -> None:
        self._stop.set()
        if self._heartbeat:
            self._heartbeat.join(timeout=1.0)

    # ── observability ───────────────────────────────────────────────────────────
    def dashboard(self) -> dict:
        cams = []
        with self._lock:
            records = list(self._records.values())
        for rec in records:
            cams.append({**rec.info.to_dict(), "health": rec.health.snapshot(),
                         "queue": rec.queue.stats()})
        return {"title": "Vision Transport", "cameras": cams,
                "camera_count": len(cams), "transport": self.metrics.snapshot()}

    def health(self) -> dict:
        infos = self.list()
        degraded = [i.camera_id for i in infos
                    if i.status in (CameraStatus.DEGRADED.value, CameraStatus.DISCONNECTED.value)]
        return {"status": "ok" if not degraded else "degraded",
                "cameras": len(infos), "degraded": degraded}

    def attach(self, runtime) -> None:
        self._runtime = runtime
        try:
            runtime.register_health("vision_transport", self.health)
        except Exception:  # noqa: BLE001
            log.debug("attach failed", exc_info=True)

    def _emit(self, event: VisionEvent, data: dict) -> None:
        if self._runtime is None:
            return
        try:
            self._runtime.emit(event, data=data, source="vision")
        except Exception:  # noqa: BLE001
            log.debug("event emit failed", exc_info=True)

    def close(self) -> None:
        self.stop()
        for cid in list(self._records.keys()):
            self.remove(cid)
        self._registry.close()
