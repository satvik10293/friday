"""
core/vision/transport/adapters/webcam_adapter.py — FRIDAY 6.1 (M14)
Pull adapters for locally-attached and network cameras via OpenCV VideoCapture
(USB/laptop webcams and RTSP/network streams). OpenCV is imported lazily, so this
module is safe to import without it; `open()` raises a clear error if it is missing.
"""

from __future__ import annotations

import importlib.util
import time
from typing import Optional

from ..camera import CameraKind
from ..frame import Frame, frame_from_array
from .base import CameraAdapter


class WebcamAdapter(CameraAdapter):
    kind = CameraKind.USB_WEBCAM
    pull = True

    def __init__(self, key: str, source=0, *, label: str = "", target_fps: float = 15.0) -> None:
        super().__init__(key, label=label, target_fps=target_fps)
        self._source = source
        self._cap = None
        self._n = 0

    def open(self) -> None:  # pragma: no cover - requires a real camera
        if importlib.util.find_spec("cv2") is None:
            raise RuntimeError("OpenCV (cv2) is required for the webcam adapter")
        import cv2
        self._cap = cv2.VideoCapture(self._source)
        self._open = bool(self._cap.isOpened())
        if not self._open:
            raise RuntimeError(f"could not open camera source {self._source!r}")

    def read(self) -> Optional[Frame]:  # pragma: no cover - requires a real camera
        if not self._open or self._cap is None:
            return None
        ok, image = self._cap.read()
        if not ok or image is None:
            return None
        self._n += 1
        return frame_from_array(self.camera_id or "", image, frame_number=self._n,
                                receive_time=time.time())

    def close(self) -> None:  # pragma: no cover
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._open = False


class RtspAdapter(WebcamAdapter):
    """Network / RTSP camera. `source` is the stream URL."""
    kind = CameraKind.RTSP

    def __init__(self, key: str, url: str, *, label: str = "", target_fps: float = 15.0) -> None:
        super().__init__(key, source=url, label=label, target_fps=target_fps)
