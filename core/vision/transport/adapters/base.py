"""
core/vision/transport/adapters/base.py — FRIDAY 6.1 (M14)
The camera adapter contract. An adapter's sole job is to *produce decoded Frames*
when the Camera Manager polls `read()`. It never enqueues, scores health, or touches
the rest of the system — that is the manager's job. Two flavours:

  • CameraAdapter (pull) — captures a frame on read() (webcam, RTSP, array).
  • PushAdapter        — buffers externally submitted payloads; read() pops + decodes
                         (browser/SocketIO, ESP32-HTTP). Decode runs on the manager's
                         worker thread, never the socket thread.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Optional

from ..camera import CameraKind
from ..decoder import FrameDecoder
from ..frame import Frame, FrameFlags, PixelFormat, frame_from_array


class CameraAdapter:
    kind: CameraKind = CameraKind.UNKNOWN
    pull: bool = True                         # manager runs a capture loop for pull adapters

    def __init__(self, key: str, *, label: str = "", target_fps: float = 10.0) -> None:
        self.key = key
        self.label = label or key
        self.target_fps = target_fps
        self.camera_id: Optional[str] = None  # assigned by the manager
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def read(self) -> Optional[Frame]:  # pragma: no cover - overridden
        raise NotImplementedError

    def info_metadata(self) -> dict:
        return {"kind": self.kind.value, "label": self.label}


class PushAdapter(CameraAdapter):
    """Buffers externally submitted raw payloads; the manager polls read() to decode."""

    pull = False

    def __init__(self, key: str, *, label: str = "", target_fps: float = 10.0,
                 decoder: Optional[FrameDecoder] = None, buffer: int = 4) -> None:
        super().__init__(key, label=label, target_fps=target_fps)
        self._decoder = decoder
        self._raw: deque = deque(maxlen=max(1, buffer))
        self._lock = threading.Lock()
        self._n = 0

    def set_decoder(self, decoder: FrameDecoder) -> None:
        self._decoder = decoder

    def submit(self, payload, *, capture_time: float = 0.0,
               recv_time: Optional[float] = None) -> None:
        """Called by the external producer (e.g. the SocketIO handler). Fast: only
        buffers; decoding happens later on the manager's worker thread."""
        with self._lock:
            self._raw.append((payload, capture_time,
                              recv_time if recv_time is not None else time.time()))

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._raw)

    def read(self) -> Optional[Frame]:
        with self._lock:
            item = self._raw.popleft() if self._raw else None
        if item is None:
            return None
        payload, capture_time, recv_time = item
        self._n += 1
        arr = self._decoder.decode(payload) if self._decoder is not None else None
        if arr is None:                       # corruption is data, not a crash
            f = Frame(camera_id=self.camera_id or "", frame_number=self._n,
                      pixel_format=PixelFormat.UNKNOWN.value, compression="jpeg",
                      capture_time=capture_time, receive_time=recv_time,
                      flags=FrameFlags(corrupt=True, decoded=False))
            f.compute_latency()
            return f
        return frame_from_array(self.camera_id or "", arr, frame_number=self._n,
                                compression="jpeg", capture_time=capture_time,
                                receive_time=recv_time)
