"""
core/vision/processing/face.py — FRIDAY 6.1 (M14)
Face detection + a face-recognition hook.

`FaceDetector` uses OpenCV's bundled Haar cascade (no model download — the cascade
ships with opencv), so it is genuinely available whenever cv2 is installed. It emits
`face` detections with bounding boxes.

`FaceRecognitionProcessor` is a true hook: it consumes the face detections from earlier
in the frame and, IF an embedder + gallery are injected, attaches an identity candidate
(stable-id-ready) to each face. With no embedder it reports unavailable — recognition is
opt-in and never guesses. Recognition produces *candidates only*; resolving a face to a
permanent person entity happens downstream in the Cognitive Bridge.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from .base import BoundingBox, Detection, VisionProcessor, to_gray
from .pipeline import VisionPipeline


class FaceDetector(VisionProcessor):
    name = "face"
    kind = "face_detection"
    requires = ("cv2",)

    def __init__(self, config=None) -> None:
        super().__init__()
        self._scale = float(getattr(config, "face_scale_factor", 1.1))
        self._neighbors = int(getattr(config, "face_min_neighbors", 5))
        self._cascade = None

    def warmup(self) -> None:
        if self._cascade is None:
            import cv2  # type: ignore
            path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._cascade = cv2.CascadeClassifier(path)

    def analyze(self, frame):
        import cv2  # type: ignore
        if self._cascade is None:
            self.warmup()
        gray = to_gray(frame.data).astype(np.uint8)
        faces = self._cascade.detectMultiScale(gray, scaleFactor=self._scale,
                                               minNeighbors=self._neighbors)
        detections: list = []
        for (x, y, w, h) in faces:
            detections.append(Detection(
                label="face", confidence=0.7, kind="face",
                bbox=BoundingBox(int(x), int(y), int(w), int(h)),
                attributes={"recognized": False}))
        return detections, {"faces": len(detections)}


class FaceRecognitionProcessor(VisionProcessor):
    """Hook: turns face boxes into identity candidates when an embedder is injected."""

    name = "face_recognition"
    kind = "face_recognition"
    requires = ()                              # the gate is the injected embedder, not a module

    def __init__(self, config=None) -> None:
        super().__init__()
        self._embedder: Optional[Callable] = None
        self._gallery: dict[str, np.ndarray] = {}
        self._threshold = 0.6

    def set_embedder(self, embedder: Callable, *, gallery: Optional[dict] = None,
                     threshold: float = 0.6) -> None:
        """Inject a callable face-image → embedding vector, plus an optional known-faces
        gallery {label: vector}. This is the integration point for a real face model."""
        self._embedder = embedder
        self._gallery = dict(gallery or {})
        self._threshold = threshold

    def available(self) -> bool:
        return self._embedder is not None

    def enroll(self, label: str, vector) -> None:
        self._gallery[label] = np.asarray(vector, dtype=np.float32)

    def analyze(self, frame):
        faces = [d for d in VisionPipeline.pipeline_detections(frame)
                 if d.kind == "face" and d.bbox is not None]
        img = np.asarray(frame.data)
        recognized = 0
        for face in faces:
            b = face.bbox
            crop = img[max(0, b.y):b.y + b.h, max(0, b.x):b.x + b.w]
            if crop.size == 0:
                continue
            vec = np.asarray(self._embedder(crop), dtype=np.float32)
            label, score = self._match(vec)
            face.attributes["recognized"] = label is not None
            if label is not None:
                face.label = label
                face.kind = "person"
                face.attributes["identity"] = label
                face.attributes["identity_score"] = round(score, 4)
                recognized += 1
        return [], {"faces": len(faces), "recognized": recognized,
                    "gallery_size": len(self._gallery)}

    def _match(self, vec: np.ndarray):
        best_label, best_score = None, 0.0
        for label, ref in self._gallery.items():
            score = self._cosine(vec, ref)
            if score > best_score:
                best_label, best_score = label, score
        if best_label is not None and best_score >= self._threshold:
            return best_label, best_score
        return None, best_score

    @staticmethod
    def _cosine(a: np.ndarray, b: np.ndarray) -> float:
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        return float(a.dot(b) / (na * nb)) if na and nb else 0.0
