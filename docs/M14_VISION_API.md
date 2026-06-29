# M14 — Vision System API

All paths are under `core.vision`. Import is side-effect-free; nothing starts until
`start()`.

---

## VisionSystem (facade)

```python
from core.vision import VisionSystem, VisionConfig

vs = VisionSystem(
    config=VisionConfig(),     # optional; defaults are production-sane
    runtime=runtime,           # optional core.runtime.Runtime (events + health)
    perception=None,           # optional core.perception.PerceptionManager
    cognition=cognition_core,  # optional core.cognition_core.CognitionCore
    attention=attention,       # optional core.attention.AttentionSystem
    world_model=world_model,   # optional core.world.WorldModel
    transport=None,            # optional pre-built VisionTransport
)
```

> If `perception` is omitted but `cognition` + `world_model` are supplied, the system
> builds a `PerceptionManager` over `cognition.resolving_world_feed(world_model)` — so
> observations are resolved to permanent entity ids and written to the World Model
> through the sanctioned path automatically.

### Camera registration (delegates to transport)
| Method | Returns | Notes |
|---|---|---|
| `connect_browser(token, *, label="")` | `camera_id` | Android/iPhone/laptop browser camera (push). |
| `add_webcam(source=0, *, label="")` | `camera_id` | USB/laptop webcam (OpenCV, pull). |
| `add_rtsp(url, *, label="")` | `camera_id` | RTSP/network stream (pull). |
| `add_array_camera(key, frames, *, loop=False, label="")` | `camera_id` | In-memory frames (test/offline). |
| `register(adapter)` | `camera_id` | Any custom `CameraAdapter`/`PushAdapter`. |
| `remove(camera_id)` | `bool` | |
| `submit_raw(camera_id, payload, **kw)` | `bool` | Push a raw JPEG/data-URL (decoded off the socket thread). |
| `server(**kw)` | `VisionTransportServer` | Flask+SocketIO ingress. |

### Processing & lifecycle
| Method | Returns | Notes |
|---|---|---|
| `start(*, warmup=False)` | `self` | Starts transport + the dedicated processing thread. |
| `stop()` | | Stops processing thread + transport. |
| `close()` | | Full teardown (closes Visual Memory). |
| `process_camera(camera_id)` | `dict` | Consume one Frame → pipeline → builder → bridge. **Never raises.** |
| `process_all()` | `list[dict]` | One cycle across all cameras. |
| `warmup()` | | Pre-load processor backends off the hot path. |

`process_camera` result: `{camera_id, frame: bool, frame_id, detections, observations,
total_ms, promoted, events}`.

### Observability
| Method | Returns |
|---|---|
| `dashboard()` | full nested status (transport, pipeline, scene, visual_memory, bridge, processing). |
| `metrics()` | counters across stages. |
| `health()` | `{status: "ok"|"degraded", …}`. |
| `manifest()` | `architecture.json` as a dict. |
| `attach(runtime)` | registers `vision` health + attaches transport. |

Singleton: `from core.vision.service import get_vision_system; get_vision_system(**kw)`.

---

## Processing pipeline

```python
from core.vision.processing import VisionPipeline, default_registry, VisionProcessor
from core.vision.config import VisionConfig

reg = default_registry(VisionConfig().processing)
pipe = VisionPipeline([reg.create(n) for n in ("scene_stats", "motion", "tracking")])
result = pipe.process(frame)          # -> ProcessingResult
result.detections()                   # list[Detection]  (ok processors only)
result.data_for("motion")             # {"motion": bool, "motion_score": float, ...}
```

### Writing a custom processor
```python
from core.vision.processing.base import VisionProcessor, Detection, BoundingBox

class RedBlobDetector(VisionProcessor):
    name = "red_blob"
    kind = "object_detection"
    requires = ()                     # importable modules this processor needs

    def analyze(self, frame):
        # return (detections, data); NEVER raise — the base wraps timing + errors
        return [Detection("red", 0.9, kind="object",
                          bbox=BoundingBox(10, 10, 20, 20))], {"blobs": 1}

reg.register("red_blob", lambda: RedBlobDetector())
```
Add `"red_blob"` to `config.processing.enabled` to activate it. The base class provides
the never-raises guarantee, timing, availability gating, and metrics.

---

## Observation Builder

```python
from core.vision.observation import ObservationBuilder
obs = ObservationBuilder(VisionConfig().observation).build(result, frame)  # list[Observation]
```
Produces `core.perception.Observation` objects (`type=VISION`) — the same type every
other sensor emits.

---

## Cognitive Bridge

```python
from core.vision.integration import CognitiveBridge, VisionCognitionEvent
bridge = CognitiveBridge(perception=..., cognition=..., attention=...,
                         scene_graph=..., visual_memory=..., runtime=...)
out = bridge.process(result, observations, frame)
# out: {camera_id, ingested, promoted, linked, events: [...], stable_ids: {track_id: ENT_id}}
```

---

## Scene Graph

```python
from core.vision.scene import SceneGraph
sg = SceneGraph(VisionConfig().scene)
sg.update(camera_id, detections, width, height)        # upsert tracked objects
sg.relationships(camera_id)                            # spatial relations
sg.camera_position(camera_id, object_id)               # normalized
sg.set_calibration(camera_id, lambda x, y: (X, Y, Z))  # → world_position(...)
sg.set_room_mapper(lambda cam: "office")               # room hook
sg.snapshot()                                          # Mission Control payload
```

---

## Visual Memory

```python
from core.vision.memory import VisualMemory
vm = VisualMemory("data/visual_memory.db", significance_threshold=0.55)
vm.remember_observation(observation, significance)     # stored iff >= threshold
vm.record_event(camera_id, "vision.motion.started", subject=..., data=...)
vm.record_sighting(stable_id=..., track_id=..., camera_id=..., label=..., center=(x, y))
vm.record_scene_change(camera_id, magnitude, data=...)
vm.recent_observations(limit, camera_id); vm.object_history(stable_id); vm.scene_changes(camera_id)
```

---

## Mission Control

```python
from core.vision.mission_control import VisionPanel
panel = VisionPanel(vision_system).panel()             # cameras, fps, latency, queue, object_count, …
preview = VisionPanel(vision_system).preview(camera_id)  # base64 JPEG data-URL (on demand)
```
The M10 aggregator accepts `MissionControlAggregator(vision=vision_system)` and exposes
a `"vision"` panel (absent when not wired).

---

## Events (runtime bus)

Transport: `core.vision.transport.events.VisionEvent` — `vision.camera.registered/
connected/streaming/degraded/recovered/disconnected/removed`, `vision.frame.dropped/
corrupt`, `vision.transport.warning/error`.

Cognition: `core.vision.integration.events.VisionCognitionEvent` — `vision.observation`,
`vision.object.appeared/disappeared/promoted`, `vision.motion.started/stopped`,
`vision.scene.changed`, `vision.entity.linked`.
