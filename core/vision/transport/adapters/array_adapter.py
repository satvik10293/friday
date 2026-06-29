"""
core/vision/transport/adapters/array_adapter.py — FRIDAY 6.1 (M14)
A pull adapter backed by in-memory image arrays. The offline / test / synthetic
camera — drives the whole transport pipeline deterministically without hardware or
sockets.
"""

from __future__ import annotations

import time
from typing import Optional

import numpy as np

from ..camera import CameraKind
from ..frame import Frame, frame_from_array
from .base import CameraAdapter


class ArrayAdapter(CameraAdapter):
    kind = CameraKind.ARRAY
    pull = True

    def __init__(self, key: str, frames=None, *, loop: bool = False,
                 label: str = "", target_fps: float = 10.0) -> None:
        super().__init__(key, label=label, target_fps=target_fps)
        self._frames = [np.asarray(f) for f in (frames or [])]
        self._i = 0
        self._n = 0
        self._loop = loop

    def feed(self, frame: np.ndarray) -> None:
        self._frames.append(np.asarray(frame))

    def read(self) -> Optional[Frame]:
        if not self._open:
            return None
        if self._i >= len(self._frames):
            if self._loop and self._frames:
                self._i = 0
            else:
                return None
        arr = self._frames[self._i]
        self._i += 1
        self._n += 1
        return frame_from_array(self.camera_id or "", arr, frame_number=self._n,
                                receive_time=time.time())

    @property
    def remaining(self) -> int:
        return max(0, len(self._frames) - self._i)


def synthetic_frame(width: int = 64, height: int = 48, value: int = 128) -> np.ndarray:
    """A deterministic BGR test frame."""
    return np.full((height, width, 3), value, dtype=np.uint8)
