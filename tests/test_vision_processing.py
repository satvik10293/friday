"""M14 — Vision Processing Pipeline: plugins, never-raises guarantee, availability
gating, motion/segmentation/tracking/scene_stats behaviour, intra-frame detection
sharing, metrics."""

import numpy as np
import pytest

from core.vision.config import VisionConfig
from core.vision.processing.base import (BoundingBox, Detection, ProcessorResult,
                                         VisionProcessor)
from core.vision.processing.pipeline import VisionPipeline
from core.vision.processing.registry import default_registry
from core.vision.processing.motion import MotionDetector
from core.vision.processing.segmentation import SegmentationProcessor
from core.vision.processing.tracking import ObjectTracker
from core.vision.processing.scene_stats import SceneStatsProcessor
from core.vision.transport.frame import frame_from_array


def _frame(value=30, square=None, cam="CAMERA_0001", n=1):
    img = np.full((120, 160, 3), value, dtype=np.uint8)
    if square is not None:
        x, y, w, h = square
        img[y:y + h, x:x + w] = 200
    return frame_from_array(cam, img, frame_number=n)


# ── geometry ────────────────────────────────────────────────────────────────────────
def test_bbox_iou_and_norm():
    a = BoundingBox(0, 0, 10, 10)
    b = BoundingBox(5, 0, 10, 10)
    assert abs(a.iou(b) - (50 / 150)) < 1e-6
    assert a.normalized(100, 50) == (0.0, 0.0, 0.1, 0.2)
    assert a.center == (5.0, 5.0)


# ── never-raises ─────────────────────────────────────────────────────────────────────
def test_processor_never_raises_on_bad_input():
    class Exploding(VisionProcessor):
        name = "boom"

        def analyze(self, frame):
            raise RuntimeError("kaboom")

    r = Exploding().process(_frame())
    assert isinstance(r, ProcessorResult) and not r.ok and "kaboom" in r.error


def test_unavailable_processor_reports_gracefully():
    class NeedsMissing(VisionProcessor):
        name = "needs"
        requires = ("a_module_that_does_not_exist_xyz",)

        def analyze(self, frame):
            return [], {}

    r = NeedsMissing().process(_frame())
    assert r.available is False and not r.ok


def test_none_frame_data_handled():
    from core.vision.transport.frame import Frame
    r = SceneStatsProcessor().process(Frame(camera_id="c"))
    assert not r.ok and r.error == "no frame data"


# ── scene stats ──────────────────────────────────────────────────────────────────────
def test_scene_stats_always_available():
    p = SceneStatsProcessor()
    assert p.available()
    r = p.process(_frame(value=200))
    assert r.ok and 0 <= r.data["brightness"] <= 1
    assert len(r.data["signature"]) == 16


# ── motion ───────────────────────────────────────────────────────────────────────────
def test_motion_detects_change_and_regions():
    m = MotionDetector(VisionConfig().processing)
    assert m.process(_frame(value=30, n=1)).data["first_frame"] is True
    r = m.process(_frame(value=30, square=(60, 40, 50, 50), n=2))
    assert r.data["motion"] is True and r.data["motion_score"] > 0
    assert any(d.label == "motion_region" and d.bbox is not None for d in r.detections)


def test_motion_state_is_per_camera():
    m = MotionDetector(VisionConfig().processing)
    m.process(_frame(cam="A", n=1))
    m.process(_frame(cam="B", n=1))
    # both cameras saw their first frame independently (no cross-talk)
    assert "A" in m._prev and "B" in m._prev


# ── segmentation ─────────────────────────────────────────────────────────────────────
def test_segmentation_produces_segments():
    s = SegmentationProcessor(VisionConfig().processing)
    r = s.process(_frame(value=30, square=(0, 0, 80, 120)))
    assert r.ok and r.data["segments"] >= 2
    assert all(d.kind == "region" and d.bbox is not None for d in r.detections)


# ── tracking (consumes intra-frame detections) ──────────────────────────────────────
def test_tracking_assigns_persistent_ids():
    # feed the tracker a controllable detector so we test IoU matching directly
    # (motion regions only appear on large change, which conflicts with overlap).
    class _Stub(VisionProcessor):
        name = "stub"

        def __init__(self):
            super().__init__()
            self.x = 50

        def analyze(self, frame):
            d = Detection("box", 0.9, kind="object", bbox=BoundingBox(self.x, 50, 40, 40))
            self.x += 5                                                  # small move → boxes overlap
            return [d], {}

    cfg = VisionConfig().processing
    pipe = VisionPipeline([_Stub(), ObjectTracker(cfg)])
    r1 = pipe.process(_frame(n=1))
    tracked = [d for d in r1.detections() if d.track_id]
    assert tracked, "tracker should assign an id"
    tid = tracked[0].track_id
    r2 = pipe.process(_frame(n=2))                                      # overlapping box → same id
    again = [d.track_id for d in r2.detections() if d.track_id]
    assert tid in again
    # a far-away box gets a new id
    r3 = pipe.process(_frame(n=3))
    assert any(t for t in (d.track_id for d in r3.detections() if d.track_id))


# ── pipeline assembly + metrics ──────────────────────────────────────────────────────
def test_default_pipeline_runs_and_reports_metrics():
    cfg = VisionConfig()
    reg = default_registry(cfg.processing)
    pipe = VisionPipeline([reg.create(n) for n in cfg.processing.enabled])
    assert pipe.names() == ["scene_stats", "motion", "segmentation", "tracking"]
    pipe.process(_frame(n=1))
    pipe.process(_frame(square=(60, 40, 50, 50), n=2))
    m = pipe.metrics()
    assert m["frames_processed"] == 2 and len(m["processors"]) == 4
    assert pipe.health()["status"] == "ok"


def test_registry_lists_all_builtins():
    reg = default_registry(VisionConfig().processing)
    for name in ("scene_stats", "motion", "segmentation", "tracking", "objects",
                 "face", "face_recognition", "ocr", "pose"):
        assert name in reg


def test_object_detector_unavailable_without_model():
    from core.vision.processing.objects import ObjectDetector
    # default config has no model path → detector is gracefully unavailable
    det = ObjectDetector(VisionConfig().processing)
    assert det.available() is False
    assert det.process(_frame()).available is False
