"""M14 — Observation Builder: processing results become standardized
core.perception.Observation objects with the mandated fields. The builder is the only
place vision creates observations."""

import numpy as np

from core.perception.models import Observation, ObservationType
from core.vision.config import VisionConfig
from core.vision.observation.builder import ObservationBuilder
from core.vision.processing.pipeline import VisionPipeline
from core.vision.processing.registry import default_registry
from core.vision.transport.frame import frame_from_array


def _pipe():
    cfg = VisionConfig().processing
    reg = default_registry(cfg)
    return VisionPipeline([reg.create(n) for n in ("scene_stats", "motion", "tracking")])


def _frame(square=None, n=1):
    img = np.full((120, 160, 3), 30, dtype=np.uint8)
    if square:
        x, y, w, h = square
        img[y:y + h, x:x + w] = 200
    return frame_from_array("CAMERA_0001", img, frame_number=n)


def test_builds_summary_observation():
    pipe = _pipe()
    result = pipe.process(_frame(n=1))
    obs = ObservationBuilder(VisionConfig().observation).build(result, None)
    assert len(obs) == 1                                  # just the scene summary
    summary = obs[0]
    assert isinstance(summary, Observation) and summary.type == ObservationType.VISION
    assert summary.metadata["summary"] is True
    assert summary.subject() == "vision:scene:CAMERA_0001"
    assert "scene_signature" in summary.payload


def test_builds_object_observation_with_mandated_fields():
    pipe = _pipe()
    pipe.process(_frame(n=1))                             # prime motion
    frame = _frame(square=(60, 40, 50, 50), n=2)
    result = pipe.process(frame)
    obs = ObservationBuilder(VisionConfig().observation).build(result, frame)
    objects = [o for o in obs if not o.metadata.get("summary")]
    assert objects, "expected at least one object observation"
    o = objects[0]
    # mandated fields: source, entity candidates, confidence, timestamp, spatial,
    # visual evidence, processing metadata
    assert o.source.name == "vision" and o.source.kind == "camera"
    assert o.payload["entity_candidates"] and "kind" in o.payload["entity_candidates"][0]
    assert 0 <= o.confidence <= 1 and o.timestamp > 0
    assert "bbox" in o.payload["spatial"] and "bbox_norm" in o.payload["spatial"]
    assert o.payload["visual_evidence"]["checksum"] == frame.checksum
    assert o.payload["processing"]["processor"]
    assert o.metadata["entity_kind"] == "object"
    assert o.metadata["track_id"] is not None


def test_per_object_dedup_by_track():
    pipe = _pipe()
    pipe.process(_frame(n=1))
    frame = _frame(square=(60, 40, 50, 50), n=2)
    result = pipe.process(frame)
    obs = ObservationBuilder(VisionConfig().observation).build(result, frame)
    track_ids = [o.metadata.get("track_id") for o in obs if not o.metadata.get("summary")]
    assert len(track_ids) == len(set(track_ids))         # one observation per track


def test_metrics():
    b = ObservationBuilder(VisionConfig().observation)
    b.build(_pipe().process(_frame()), None)
    assert b.metrics()["observations_built"] >= 1
