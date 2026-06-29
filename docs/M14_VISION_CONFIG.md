# M14 — Vision System Configuration

All configuration lives in `core/vision/config.py` as typed, serializable dataclasses.
`VisionConfig` is the single object the `VisionSystem` reads. It is constructed from
defaults, overridden from a (partial) dict, and injected. **No tunable is hidden inside
a module.**

```python
from core.vision import VisionConfig

cfg = VisionConfig()                                  # production-sane defaults
cfg = VisionConfig.from_dict({                        # partial override (tolerant)
    "processing": {"enabled": ["scene_stats", "motion", "tracking", "face"],
                   "max_processing_fps": 6.0},
    "memory": {"persistent": True, "significance_threshold": 0.6},
})
cfg.to_dict()                                         # round-trips to JSON
```

`from_dict` is tolerant by design: unknown keys are ignored and missing sections fall
back to defaults, so a slice of `friday_config.json` can be passed directly.

---

## `transport` — TransportConfig
| Key | Default | Meaning |
|---|---|---|
| `queue_size` | `2` | Per-camera bounded queue depth. |
| `target_fps` | `10.0` | Expected frame rate (health baseline). |
| `overflow` | `"drop_oldest"` | `drop_oldest` (keep freshest) \| `drop_newest` \| `block`. |
| `persistent_registry` | `False` | `True` → camera ids persist in `data/vision.db` across restarts. |
| `registry_path` | `None` | Override the registry DB path. |

## `processing` — ProcessingConfig
| Key | Default | Meaning |
|---|---|---|
| `enabled` | `["scene_stats","motion","segmentation","tracking"]` | Ordered processor list (the tracker should come after detectors). |
| `max_processing_fps` | `8.0` | Throttle for the processing thread (kept below transport fps). |
| `workers` | `2` | Reserved for future multi-camera parallelism. |
| `motion_threshold` | `0.04` | Mean inter-frame delta (0..1) to call it motion. |
| `motion_downscale` | `64` | Work on a WxW luminance thumbnail for speed. |
| `motion_min_region` | `0.01` | Min moving-region area (fraction of frame). |
| `segmentation_grid` | `8` | GxG grid for the lightweight segmenter. |
| `segmentation_merge_tol` | `18.0` | Mean-colour L1 distance to merge adjacent cells. |
| `object_backend` | `"auto"` | `auto` \| `ultralytics` \| `opencv_dnn` \| `onnx` \| `none`. |
| `object_model_path` | `None` | **Explicit** model path (no auto-download). Detector is unavailable without it. |
| `object_labels_path` | `None` | Optional class-label file (defaults to COCO). |
| `object_confidence` | `0.35` | Detection confidence threshold. |
| `track_iou_threshold` | `0.3` | IoU above which a detection matches an existing track. |
| `track_max_age` | `30` | Frames a track survives unmatched before expiry. |
| `ocr_languages` | `["en"]` | EasyOCR languages. |
| `ocr_min_confidence` | `0.4` | Min OCR confidence to keep a region. |
| `face_scale_factor` | `1.1` | Haar cascade scale factor. |
| `face_min_neighbors` | `5` | Haar cascade min neighbours. |
| `pose_min_confidence` | `0.5` | MediaPipe pose min detection confidence. |

> **Enabling heavy/optional processors.** Add their names to `enabled`:
> - `"face"` — needs `cv2` (already present). Real face boxes, no model download.
> - `"objects"` — set `object_backend` + `object_model_path` (e.g. a YOLO `.pt` with
>   ultralytics, or a `.onnx` with OpenCV-DNN). Unavailable (graceful) without a model.
> - `"ocr"` — needs `easyocr`. Heavy; loaded lazily on warmup.
> - `"pose"` — needs `mediapipe`. Loaded lazily on warmup.
> - `"face_recognition"` — inject an embedder:
>   `system.pipeline.processors()`-> find it -> `.set_embedder(fn, gallery=...)`.

## `observation` — ObservationConfig
| Key | Default | Meaning |
|---|---|---|
| `source_name` | `"vision"` | `ObservationSource.name` stamped on every observation. |
| `min_significance` | `0.0` | Drop frame-observations below this (advisory). |
| `emit_per_detection` | `True` | Emit one observation per tracked object plus the frame summary. |
| `base_confidence` | `0.6` | Base confidence blended with detection confidence. |

## `scene` — SceneConfig
| Key | Default | Meaning |
|---|---|---|
| `near_fraction` | `0.12` | Centre distance (fraction of frame) below which two objects are `near`. |
| `overlap_relation` | `0.15` | IoU above which two objects are `overlapping`. |
| `forget_after_s` | `30.0` | Drop scene objects unseen this long. |

## `memory` — VisualMemoryConfig
| Key | Default | Meaning |
|---|---|---|
| `db_path` | `None` | Defaults to `data/visual_memory.db`. |
| `significance_threshold` | `0.55` | Store observations at/above this significance. |
| `max_object_history` | `200` | Sightings retained per object. |
| `persistent` | `True` | `False` → in-memory DB (tests). |

---

## Dependencies & graceful degradation

| Backend | Present in repo env? | Used by | Absent → |
|---|---|---|---|
| `numpy` | required | everything | n/a |
| `cv2` (OpenCV) | yes | decode, motion CC, face Haar, object DNN | numpy fallbacks where possible; face/objects report unavailable |
| `Pillow` | yes | decode fallback | cv2 used instead |
| `easyocr` | yes | `ocr` | `ocr` unavailable |
| `mediapipe` | yes | `pose` | `pose` unavailable |
| `ultralytics` | no | `objects` (one backend) | OpenCV-DNN/ONNX used, or unavailable |
| `flask` / `flask-socketio` | flask only | browser ingress server | server raises a clear error if run without socketio |

The **default pipeline requires only numpy** and is always available. Every other
processor degrades gracefully: `available()` returns `False` and the pipeline simply
skips it — never an error, never a crash.

---

## Example: full wiring

```python
from core.vision import VisionSystem, VisionConfig

vs = VisionSystem(
    config=VisionConfig.from_dict({
        "transport": {"persistent_registry": True, "target_fps": 12},
        "processing": {"enabled": ["scene_stats", "motion", "tracking", "face"]},
    }),
    runtime=runtime, cognition=cognition_core, world_model=world_model, attention=attention,
)
vs.attach(runtime)
vs.start(warmup=True)
cam = vs.connect_browser("phone-1", label="Pixel")
# ... frames arrive over SocketIO; the processing thread turns them into observations
```
