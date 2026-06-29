"""
core/vision/transport/decoder.py — FRIDAY 6.1 (M14)
Frame decoding — compressed bytes (JPEG/PNG, possibly base64 data-URL) → a decoded
image array. Pluggable backend: OpenCV when present (fastest), else Pillow, else a
raw passthrough for already-decoded data. Decoding is the one expensive transport
step, so it runs on a dedicated decoder thread (the Camera Manager drives it), never
on the socket thread. Corrupt input returns None rather than raising.
"""

from __future__ import annotations

import base64
import importlib.util
import logging
from typing import Optional

import numpy as np

log = logging.getLogger("friday.vision.decoder")


def _strip_data_url(payload) -> bytes:
    """Accept raw bytes or a base64 data-URL string ('data:image/jpeg;base64,...')."""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    s = str(payload)
    if "," in s and s.strip().startswith("data:"):
        s = s.split(",", 1)[1]
    return base64.b64decode(s)


class FrameDecoder:
    def __init__(self, backend: Optional[str] = None) -> None:
        self.backend = backend or self._select_backend()

    @staticmethod
    def _select_backend() -> str:
        if importlib.util.find_spec("cv2") is not None:
            return "cv2"
        if importlib.util.find_spec("PIL") is not None:
            return "pillow"
        return "none"

    def decode(self, payload) -> Optional[np.ndarray]:
        """Decode compressed image bytes/data-URL → BGR uint8 array, or None on
        failure. Never raises (corruption is data, not a crash)."""
        try:
            raw = _strip_data_url(payload)
        except Exception:  # noqa: BLE001
            return None
        if not raw:
            return None
        try:
            if self.backend == "cv2":
                import cv2
                arr = np.frombuffer(raw, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                return img
            if self.backend == "pillow":
                import io
                from PIL import Image
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                rgb = np.asarray(img)
                return rgb[:, :, ::-1].copy()      # RGB → BGR for consistency with cv2
        except Exception as e:  # noqa: BLE001
            log.debug("decode failed: %s", e)
            return None
        return None

    def encode_jpeg(self, image: np.ndarray, quality: int = 60) -> Optional[bytes]:
        """Encode a decoded array back to JPEG bytes (Mission Control preview)."""
        try:
            if self.backend == "cv2":
                import cv2
                ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
                return buf.tobytes() if ok else None
            if self.backend == "pillow":
                import io
                from PIL import Image
                arr = image[:, :, ::-1] if image.ndim == 3 else image   # BGR → RGB
                out = io.BytesIO()
                Image.fromarray(arr.astype(np.uint8)).save(out, format="JPEG", quality=quality)
                return out.getvalue()
        except Exception:  # noqa: BLE001
            return None
        return None
