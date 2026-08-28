"""
core/vision/transport/frame.py — FRIDAY 6.1 (M14)
The Frame object. Downstream subsystems consume Frames, never raw NumPy arrays. A
Frame carries the decoded image plus full provenance: identity, camera, timestamps,
frame number, resolution, pixel format, compression, measured latency, checksum,
flags, and health context. Reserved fields (ai_metadata, embedding, observation_ref)
are declared now — explicitly, not hidden — so later vision/cognition stages attach
to a frame without changing its shape.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np


class PixelFormat(str, Enum):
    BGR = "bgr"
    RGB = "rgb"
    GRAY = "gray"
    JPEG = "jpeg"
    RAW = "raw"
    UNKNOWN = "unknown"


@dataclass
class FrameFlags:
    corrupt: bool = False
    keyframe: bool = True
    decoded: bool = True
    dropped: bool = False

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def new_frame_id() -> str:
    return "FRM_" + uuid.uuid4().hex[:12]


@dataclass
class Frame:
    """One image frame in transit through the Cognitive OS."""
    camera_id: str
    frame_number: int = 0
    width: int = 0
    height: int = 0
    pixel_format: str = PixelFormat.BGR.value
    compression: str = "none"                 # source compression, e.g. "jpeg"
    timestamp: float = field(default_factory=time.time)   # when the Frame was built
    capture_time: float = 0.0                 # client-side capture time (if provided)
    receive_time: float = 0.0                 # server receive time
    latency_ms: float = 0.0
    checksum: str = ""
    data: Optional[np.ndarray] = None         # decoded image (not serialized)
    metadata: dict = field(default_factory=dict)
    flags: FrameFlags = field(default_factory=FrameFlags)
    health: dict = field(default_factory=dict)
    # ── reserved for later stages (explicit, never hidden) ──────────────────────
    ai_metadata: dict = field(default_factory=dict)
    embedding: Optional[list] = None
    observation_ref: Optional[str] = None
    frame_id: str = field(default_factory=new_frame_id)

    # ── derived ─────────────────────────────────────────────────────────────────
    @property
    def resolution(self) -> tuple:
        return (self.width, self.height)

    def compute_latency(self) -> float:
        """receive − capture, in ms (0 when capture time is unknown)."""
        if self.capture_time and self.receive_time:
            self.latency_ms = round(max(0.0, (self.receive_time - self.capture_time) * 1000.0), 3)
        return self.latency_ms

    def compute_checksum(self) -> str:
        if self.data is not None:
            self.checksum = hashlib.sha1(np.ascontiguousarray(self.data).tobytes()).hexdigest()[:16]
        return self.checksum

    def nbytes(self) -> int:
        return int(self.data.nbytes) if self.data is not None else 0

    def to_dict(self, *, include_shape: bool = True) -> dict:
        """Serializable view — the raw pixel array is never included."""
        d = {
            "frame_id": self.frame_id, "camera_id": self.camera_id,
            "frame_number": self.frame_number, "width": self.width, "height": self.height,
            "pixel_format": self.pixel_format, "compression": self.compression,
            "timestamp": self.timestamp, "capture_time": self.capture_time,
            "receive_time": self.receive_time, "latency_ms": self.latency_ms,
            "checksum": self.checksum, "metadata": self.metadata,
            "flags": self.flags.to_dict(), "health": self.health,
            "observation_ref": self.observation_ref,
        }
        if include_shape:
            d["shape"] = list(self.data.shape) if self.data is not None else None
            d["nbytes"] = self.nbytes()
        return d


def frame_from_array(camera_id: str, array: np.ndarray, *, frame_number: int = 0,
                     pixel_format: str = PixelFormat.BGR.value, compression: str = "none",
                     capture_time: float = 0.0, receive_time: Optional[float] = None,
                     metadata: Optional[dict] = None) -> Frame:
    """Build a Frame from a decoded image array, filling resolution + latency +
    checksum. The single sanctioned constructor for decoded frames."""
    arr = np.asarray(array)
    h, w = (arr.shape[0], arr.shape[1]) if arr.ndim >= 2 else (0, 0)
    recv = receive_time if receive_time is not None else time.time()
    frame = Frame(camera_id=camera_id, frame_number=frame_number, width=int(w), height=int(h),
                  pixel_format=pixel_format, compression=compression,
                  capture_time=capture_time, receive_time=recv,
                  data=arr, metadata=dict(metadata or {}))
    frame.compute_latency()
    frame.compute_checksum()
    return frame
