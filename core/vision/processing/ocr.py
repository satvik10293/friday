"""
core/vision/processing/ocr.py — FRIDAY 6.1 (M14)
Optical character recognition. Backed by EasyOCR (already a project dependency, see
models/vision/easyocr). Opt-in and lazy: the reader is heavy, so it is only constructed
on `warmup()`/first use — never at import — and the processor reports unavailable when
EasyOCR is absent. Emits one `text` detection per recognized region plus the joined
text, so the Observation Builder can surface read text as visual evidence.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .base import BoundingBox, Detection, VisionProcessor


class OCRProcessor(VisionProcessor):
    name = "ocr"
    kind = "ocr"
    requires = ("easyocr",)

    def __init__(self, config=None) -> None:
        super().__init__()
        self._langs = list(getattr(config, "ocr_languages", ["en"]) or ["en"])
        self._min_conf = float(getattr(config, "ocr_min_confidence", 0.4))
        self._reader = None

    def warmup(self) -> None:
        if self._reader is None:
            import easyocr  # type: ignore
            self._reader = easyocr.Reader(self._langs, gpu=False, verbose=False)

    def analyze(self, frame):
        if self._reader is None:
            self.warmup()
        img = np.asarray(frame.data)
        results = self._reader.readtext(img)
        detections: list = []
        texts: list[str] = []
        for box, text, conf in results:
            if float(conf) < self._min_conf or not str(text).strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y = int(min(xs)), int(min(ys))
            w, h = int(max(xs) - x), int(max(ys) - y)
            detections.append(Detection(
                label="text", confidence=float(conf), kind="text",
                bbox=BoundingBox(x, y, w, h),
                attributes={"text": str(text)}))
            texts.append(str(text))
        return detections, {"regions": len(detections), "text": " ".join(texts)}
