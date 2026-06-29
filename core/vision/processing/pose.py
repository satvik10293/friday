"""
core/vision/processing/pose.py — FRIDAY 6.1 (M14)
Human pose estimation via MediaPipe (already a project dependency — see the gesture
system). Opt-in and lazy: the detector is constructed on first use, not at import, and
the processor reports unavailable when MediaPipe is missing. Emits a `person` detection
with a pose bounding box and normalized landmarks, giving downstream stages body-pose
evidence without any reasoning here.
"""

from __future__ import annotations

import numpy as np

from .base import BoundingBox, Detection, VisionProcessor


class PoseEstimator(VisionProcessor):
    name = "pose"
    kind = "pose"
    requires = ("mediapipe",)

    def __init__(self, config=None) -> None:
        super().__init__()
        self._min_conf = float(getattr(config, "pose_min_confidence", 0.5))
        self._pose = None

    def warmup(self) -> None:
        if self._pose is None:
            import mediapipe as mp  # type: ignore
            self._pose = mp.solutions.pose.Pose(
                static_image_mode=True, min_detection_confidence=self._min_conf)

    def analyze(self, frame):
        if self._pose is None:
            self.warmup()
        img = np.asarray(frame.data)
        # mediapipe expects RGB; frames are BGR by convention
        rgb = img[:, :, ::-1] if img.ndim == 3 else np.stack([img] * 3, -1)
        result = self._pose.process(np.ascontiguousarray(rgb))
        landmarks = getattr(result, "pose_landmarks", None)
        if landmarks is None:
            return [], {"persons": 0}
        h, w = img.shape[:2]
        pts = [(lm.x, lm.y, lm.visibility) for lm in landmarks.landmark]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, y1, x2, y2 = min(xs) * w, min(ys) * h, max(xs) * w, max(ys) * h
        det = Detection(
            label="person", confidence=float(np.mean([p[2] for p in pts])), kind="person",
            bbox=BoundingBox(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
            attributes={"landmarks": [[round(p[0], 4), round(p[1], 4), round(p[2], 3)]
                                      for p in pts]})
        return [det], {"persons": 1}
