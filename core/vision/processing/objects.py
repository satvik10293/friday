"""
core/vision/processing/objects.py — FRIDAY 6.1 (M14)
Learned object detection. This is the seam where a real detector plugs in. It is
opt-in and degrades gracefully: with no model configured (the default) it reports
``available() == False`` and the pipeline relies on motion-region proposals instead;
with a model it runs full inference. Two production backends are implemented:

  • ultralytics YOLO  — `object_backend="ultralytics"` + `object_model_path=*.pt`
  • OpenCV DNN (ONNX) — `object_backend="opencv_dnn"`/`"onnx"` + `*.onnx` + labels

Nothing is auto-downloaded at import or warmup — models are referenced by explicit path
only, so the Cognitive Core never blocks or reaches the network because of vision.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from .base import BoundingBox, Detection, VisionProcessor

log = logging.getLogger("friday.vision.objects")

# Default COCO labels (used when no labels file is supplied).
_COCO = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis",
    "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
    "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife",
    "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]


class ObjectDetector(VisionProcessor):
    name = "objects"
    kind = "object_detection"

    def __init__(self, config=None) -> None:
        super().__init__()
        self._cfg = config
        self._model_path = getattr(config, "object_model_path", None)
        self._labels_path = getattr(config, "object_labels_path", None)
        self._backend_pref = getattr(config, "object_backend", "auto")
        self._conf = float(getattr(config, "object_confidence", 0.35))
        self._backend: Optional[str] = None
        self._model = None
        self._net = None
        self._labels = list(_COCO)

    # ── availability: a usable backend + an explicit model path ──────────────────
    def _resolve_backend(self) -> Optional[str]:
        if self._backend is not None:
            return self._backend or None
        pref = self._backend_pref
        has_model = bool(self._model_path) and Path(str(self._model_path)).exists()
        chosen = ""
        if has_model:
            ultra = importlib.util.find_spec("ultralytics") is not None
            cv2 = importlib.util.find_spec("cv2") is not None
            if pref in ("auto", "ultralytics") and ultra:
                chosen = "ultralytics"
            elif pref in ("auto", "opencv_dnn", "onnx") and cv2:
                chosen = "opencv_dnn"
        self._backend = chosen
        return chosen or None

    def available(self) -> bool:
        return self._resolve_backend() is not None

    def warmup(self) -> None:
        backend = self._resolve_backend()
        if backend == "ultralytics" and self._model is None:
            from ultralytics import YOLO  # type: ignore
            self._model = YOLO(str(self._model_path))
        elif backend == "opencv_dnn" and self._net is None:
            import cv2  # type: ignore
            self._net = cv2.dnn.readNet(str(self._model_path))
            if self._labels_path and Path(str(self._labels_path)).exists():
                self._labels = Path(str(self._labels_path)).read_text(
                    encoding="utf-8").splitlines()

    # ── inference ────────────────────────────────────────────────────────────────
    def analyze(self, frame):
        backend = self._resolve_backend()
        if backend == "ultralytics":
            return self._run_ultralytics(frame)
        if backend == "opencv_dnn":
            return self._run_opencv_dnn(frame)
        return [], {}

    def _run_ultralytics(self, frame):
        if self._model is None:
            self.warmup()
        results = self._model.predict(np.asarray(frame.data), verbose=False,
                                      conf=self._conf)
        detections: list = []
        for res in results:
            names = getattr(res, "names", {}) or {}
            for box in getattr(res, "boxes", []) or []:
                conf = float(box.conf[0])
                cls = int(box.cls[0])
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
                label = names.get(cls, str(cls))
                detections.append(self._det(label, conf, x1, y1, x2, y2))
        return detections, {"backend": "ultralytics", "objects": len(detections)}

    def _run_opencv_dnn(self, frame):
        import cv2  # type: ignore
        if self._net is None:
            self.warmup()
        img = np.asarray(frame.data)
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(img, 1 / 255.0, (640, 640), swapRB=True, crop=False)
        self._net.setInput(blob)
        out = self._net.forward()
        boxes, confs, classes = self._parse_yolo(out, w, h)
        detections: list = []
        if boxes:
            idxs = cv2.dnn.NMSBoxes(boxes, confs, self._conf, 0.45)
            for i in np.array(idxs).flatten():
                x, y, bw, bh = boxes[i]
                label = self._labels[classes[i]] if classes[i] < len(self._labels) else str(classes[i])
                detections.append(Detection(
                    label=label, confidence=float(confs[i]),
                    kind="person" if label == "person" else "object",
                    bbox=BoundingBox(int(x), int(y), int(bw), int(bh)),
                    attributes={"backend": "opencv_dnn"}))
        return detections, {"backend": "opencv_dnn", "objects": len(detections)}

    def _parse_yolo(self, out: np.ndarray, w: int, h: int):
        """Generic YOLOv5/v8 output parser → (boxes[xywh], confidences, class ids)."""
        arr = np.squeeze(out)
        if arr.ndim != 2:
            return [], [], []
        # v8 exports [84, 8400] (transposed); v5 exports [25200, 85].
        if arr.shape[0] < arr.shape[1]:
            arr = arr.T
        ncols = arr.shape[1]
        sx, sy = w / 640.0, h / 640.0
        boxes, confs, classes = [], [], []
        v5 = ncols >= 85 and not np.allclose(arr[:, 4].max(initial=0.0), 0.0) and ncols == 85
        for row in arr:
            cx, cy, bw, bh = row[:4]
            if v5:
                obj = row[4]
                scores = row[5:]
                cid = int(np.argmax(scores))
                conf = float(obj * scores[cid])
            else:                              # v8: no objectness, class scores at [4:]
                scores = row[4:]
                cid = int(np.argmax(scores))
                conf = float(scores[cid])
            if conf < self._conf:
                continue
            x = (cx - bw / 2) * sx
            y = (cy - bh / 2) * sy
            boxes.append([int(x), int(y), int(bw * sx), int(bh * sy)])
            confs.append(conf)
            classes.append(cid)
        return boxes, confs, classes

    def _det(self, label, conf, x1, y1, x2, y2) -> Detection:
        return Detection(label=label, confidence=conf,
                         kind="person" if label == "person" else "object",
                         bbox=BoundingBox(int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                         attributes={"backend": "ultralytics"})
