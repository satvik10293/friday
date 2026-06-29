"""M14 — Scene Graph: persistent objects, spatial relationships, camera/world
positions, room hooks, forgetting."""

import time

from core.vision.config import VisionConfig
from core.vision.processing.base import BoundingBox, Detection
from core.vision.scene.scene_graph import SceneGraph


def _det(track_id, x, y, w=20, h=20, label="object", kind="object"):
    return Detection(label=label, confidence=0.7, kind=kind,
                     bbox=BoundingBox(x, y, w, h), track_id=track_id)


def test_persistent_objects_and_sightings():
    sg = SceneGraph(VisionConfig().scene)
    sg.update("CAM", [_det("T1", 10, 10)], 100, 100)
    sg.update("CAM", [_det("T1", 12, 12)], 100, 100)        # same track → one object, 2 sightings
    objs = sg.objects("CAM")
    assert len(objs) == 1 and objs[0]["sightings"] == 2
    assert objs[0]["object_id"] == "T1"


def test_only_objects_become_scene_nodes():
    sg = SceneGraph(VisionConfig().scene)
    sg.update("CAM", [_det("T1", 10, 10, kind="region", label="segment"),
                      _det("T2", 50, 50, kind="object")], 100, 100)
    assert {o["object_id"] for o in sg.objects("CAM")} == {"T2"}


def test_spatial_relationships():
    sg = SceneGraph(VisionConfig().scene)
    sg.update("CAM", [_det("L", 10, 40), _det("R", 70, 40)], 100, 100)
    rels = sg.relationships("CAM")
    kinds = {r["relation"] for r in rels}
    assert "left_of" in kinds or "right_of" in kinds


def test_camera_and_world_positions_with_calibration():
    sg = SceneGraph(VisionConfig().scene)
    sg.update("CAM", [_det("T1", 40, 40, 20, 20)], 100, 100)
    cam_pos = sg.camera_position("CAM", "T1")
    assert cam_pos["frame"] == "camera" and abs(cam_pos["x"] - 0.5) < 1e-6
    # without calibration → camera frame, flagged uncalibrated
    assert sg.world_position("CAM", "T1")["calibrated"] is False
    sg.set_calibration("CAM", lambda x, y: (x * 10, y * 10, 1.0))
    wp = sg.world_position("CAM", "T1")
    assert wp["frame"] == "world" and wp["calibrated"] is True and wp["x"] == 5.0


def test_room_mapping_hook():
    sg = SceneGraph(VisionConfig().scene)
    assert sg.room_for("CAM") == "unknown"
    sg.set_room_mapper(lambda cam: "office")
    assert sg.room_for("CAM") == "office"


def test_stable_id_linking_and_snapshot():
    sg = SceneGraph(VisionConfig().scene)
    sg.update("CAM", [_det("T1", 10, 10)], 100, 100)
    sg.set_stable_id("CAM", "T1", "ENT_000001")
    snap = sg.snapshot()
    assert snap["object_count"] == 1
    assert snap["scenes"][0]["objects"][0]["stable_id"] == "ENT_000001"


def test_forgets_stale_objects():
    cfg = VisionConfig().scene
    cfg.forget_after_s = 0.0
    sg = SceneGraph(cfg)
    sg.update("CAM", [_det("T1", 10, 10)], 100, 100, timestamp=time.time() - 10)
    sg.update("CAM", [_det("T2", 50, 50)], 100, 100, timestamp=time.time())
    assert {o["object_id"] for o in sg.objects("CAM")} == {"T2"}
