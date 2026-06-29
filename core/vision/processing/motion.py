"""
core/vision/processing/motion.py — FRIDAY 6.1 (M14)
Motion detection + moving-region proposals. Always-available (pure numpy): it keeps a
small per-camera luminance thumbnail of the previous frame and reports the mean
inter-frame delta plus bounding boxes of regions that changed. The region proposals
double as cheap, model-free "object" candidates for the tracker when no learned
detector is configured — motion is the most basic visual signal that *something* is
there.

State is per camera and lives in the processor (never on the immutable Frame).
"""

from __future__ import annotations

import numpy as np

from .base import BoundingBox, Detection, VisionProcessor, downscale, to_gray


class MotionDetector(VisionProcessor):
    name = "motion"
    kind = "motion"
    requires = ()

    def __init__(self, config=None) -> None:
        super().__init__()
        self._threshold = getattr(config, "motion_threshold", 0.04)
        self._size = int(getattr(config, "motion_downscale", 64))
        self._min_region = getattr(config, "motion_min_region", 0.01)
        self._prev: dict[str, np.ndarray] = {}

    def analyze(self, frame):
        gray = to_gray(frame.data)
        thumb = downscale(gray, self._size)
        prev = self._prev.get(frame.camera_id)
        self._prev[frame.camera_id] = thumb
        if prev is None or prev.shape != thumb.shape:
            return [], {"motion": False, "motion_score": 0.0, "regions": 0, "first_frame": prev is None}

        delta = np.abs(thumb - prev)
        score = float(delta.mean()) / 255.0
        motion = score >= self._threshold
        detections: list = []
        regions = 0
        if motion:
            mask = delta > (delta.mean() + delta.std())
            detections = self._regions(mask, frame.width, frame.height)
            regions = len(detections)
        return detections, {"motion": motion, "motion_score": round(score, 5),
                            "regions": regions}

    def _regions(self, mask: np.ndarray, width: int, height: int) -> list:
        """Connected-component bounding boxes on the thumbnail mask, scaled back to the
        full frame. cv2 is used when present (fast + accurate); otherwise a numpy
        row/column projection gives a single coarse region (still real, never a stub)."""
        mh, mw = mask.shape[:2]
        if mw == 0 or mh == 0 or not mask.any():
            return []
        sx = width / mw if mw else 1.0
        sy = height / mh if mh else 1.0
        boxes: list[tuple[int, int, int, int]] = []
        try:
            import cv2  # type: ignore
            n, _labels, stats, _cent = cv2.connectedComponentsWithStats(
                mask.astype(np.uint8), connectivity=8)
            for i in range(1, n):
                x, y, w, h, area = stats[i]
                if area <= 0:
                    continue
                boxes.append((int(x), int(y), int(w), int(h)))
        except Exception:  # noqa: BLE001 — numpy fallback
            ys, xs = np.where(mask)
            boxes.append((int(xs.min()), int(ys.min()),
                          int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))

        min_area = self._min_region * width * height
        out: list = []
        for (x, y, w, h) in boxes:
            fx, fy = int(x * sx), int(y * sy)
            fw, fh = max(1, int(w * sx)), max(1, int(h * sy))
            if fw * fh < min_area:
                continue
            out.append(Detection(label="motion_region", confidence=0.5, kind="object",
                                 bbox=BoundingBox(fx, fy, fw, fh),
                                 attributes={"source": "motion"}))
        return out
