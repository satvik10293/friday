# M14 — Vision System (FRIDAY 6.1)

> **Status:** complete. **Purpose:** *visual perception*, not computer vision. Every
> camera frame eventually becomes a structured `Observation` that improves the World
> Model. Vision is a **perception subsystem only** — it builds observations and never
> reasons, plans, predicts, simulates, or writes the World Model directly.

---

## 1. Where M14 sits in the pipeline

```
Reality → Camera → Vision Transport → Camera Manager → Frame →
  Vision Processing Pipeline → Observation Builder →
  Cognitive Bridge ( Attention → Entity Resolver → Persistent Entity IDs → World Model ) →
  Scene Graph + Visual Memory →
  Knowledge → Memory → Reasoning → Executive → Planner → Prediction → Simulation → Action
```

Nothing bypasses this pipeline. Vision's responsibility ends when it has produced
`Observation` objects and routed them through the **same** Attention → Perception →
Entity Resolver → World Model path every other sensor uses (M5/M6/M13). The downstream
cognitive stages are untouched and unaware that the evidence came from a camera.

---

## 2. Subsystem map (`core/vision/`)

| Stage | Package / module | Role |
|---|---|---|
| **Transport** (Part 1) | `transport/` | Move frames into the COS as rich `Frame` objects via the Camera Manager. Flask+SocketIO ingress, adapters, decoder, queue, health, registry, metrics. *Zero cognition.* |
| **Processing** | `processing/` | Modular processor plugins turn a `Frame` into labelled `Detection`s + structured data. |
| **Observation** | `observation/` | The single place vision builds `core.perception.Observation` objects. |
| **Integration** | `integration/` | The **Cognitive Bridge** — routes observations into cognition, links scene objects to stable ids, emits visual events. |
| **Scene** | `scene/` | Live per-camera **Scene Graph**: persistent objects, spatial relationships, camera/world positions, room hooks. |
| **Memory** | `memory/` | **Visual Memory** (SQLite): significant observations, visual events, object histories, scene changes. |
| **Facade** | `service.py` | `VisionSystem` composes every stage; processing runs on its **own** thread. |
| **Mission Control** | `mission_control.py` | Cockpit vision panel + on-demand live preview. |
| **Config** | `config.py` | Typed, injectable `VisionConfig` (per-stage). |
| **Benchmark** | `benchmark.py` | Deterministic throughput/latency benchmarks. |
| **Manifest** | `architecture.json` | Machine-readable architecture record (single source of truth). |

---

## 3. The Frame object

Downstream subsystems consume **`Frame` objects, never raw NumPy arrays**. A `Frame`
(`transport/frame.py`) carries the decoded image plus full provenance: `frame_id`,
`camera_id`, `frame_number`, timestamps (`timestamp`/`capture_time`/`receive_time`),
resolution, `pixel_format`, `compression`, measured `latency_ms`, `checksum`, `flags`,
`health`, and reserved fields (`ai_metadata`, `embedding`, `observation_ref`) declared
explicitly for later stages. The pipeline uses `ai_metadata` as a per-frame scratch
channel so order-dependent processors (the tracker) can read earlier detectors' output
within one frame.

---

## 4. Processing pipeline

Each processor is an **independent plugin** (`processing/base.py::VisionProcessor`) that
declares the backends it needs, reports `available()`, and **never raises** — a faulty
or missing-backend processor degrades to an error/unavailable result. Adding a
capability = add a plugin + register a factory; the pipeline is unchanged.

| Processor | Availability | Output |
|---|---|---|
| `scene_stats` | **always** (numpy) | brightness/contrast/sharpness/dominant colour + a 4×4 luminance signature |
| `motion` | **always** (numpy; cv2 accelerates) | motion flag/score + moving-region proposals (model-free object candidates) |
| `segmentation` | **always** (numpy) | coarse colour segments (grid + union-find) |
| `tracking` | **always** (numpy) | persistent per-camera track ids (greedy IoU), velocity, age |
| `objects` | model-gated | labelled objects via ultralytics **or** OpenCV-DNN/ONNX (explicit model path only) |
| `face` | cv2 | face boxes (bundled Haar cascade — no download) |
| `face_recognition` | embedder-gated | identity candidates (hook: inject an embedder + gallery) |
| `ocr` | easyocr | text regions + joined text |
| `pose` | mediapipe | person + normalized landmarks |

The **default** pipeline is `scene_stats → motion → segmentation → tracking`:
dependency-light, always-available, and fast (~3 ms/frame, ~290 fps on CPU). Heavier /
model-dependent processors are opt-in via `config.processing.enabled`.

> **No model is ever auto-downloaded** at import or warmup. Models are referenced by
> explicit path, so the Cognitive Core never blocks or reaches the network for vision.

---

## 5. Observation Builder

`observation/builder.py` converts a `ProcessingResult` into standardized
`core.perception.Observation` objects (`type = VISION`). Each carries the mandated
fields:

- **source** — `ObservationSource("vision", kind="camera")`
- **entity candidates** — `payload["entity_candidates"] = [{kind, name, confidence}, …]`
- **confidence**, **timestamp**
- **spatial information** — `payload["spatial"]` (`bbox`, `bbox_norm`, `center_norm`, `area_fraction`)
- **visual evidence** — `payload["visual_evidence"]` (`frame_id`, `checksum`, `resolution`, `latency_ms`)
- **processing metadata** — `payload["processing"]` (processor, attributes, durations)

Two kinds are produced: one **per persistent object** (subject keyed on the track id so
the same object dedups/merges across frames) and one **frame scene summary** (motion,
brightness, object count, scene signature). No processor builds observations.

---

## 6. Cognitive Bridge (the no-bypass guarantee)

`integration/cognitive_bridge.py` is where perception enters cognition. For each frame:

1. **Scene Graph** is updated with the tracked objects.
2. Every `Observation` is **ingested through the M6 Perception Manager**, whose
   `ResolvingWorldFeed` (M13) resolves a permanent `ENT_` stable id and writes the World
   Model — the canonical path. Vision never writes the World Model itself.
3. Scene objects are **linked to their stable ids** via the M13 Entity Linker.
4. Significant observations, sightings, and visual events are recorded in **Visual
   Memory**.
5. Observations are ranked through the **M5 Attention System**.
6. Cognition-stage **events** are emitted on the runtime bus.

Every collaborator is injected and optional; with none wired the bridge degrades to a
safe no-op that still maintains the scene graph. A failure anywhere is logged and
isolated — **a vision failure can never crash the Cognitive Core.**

Promotion to the World Model is governed by M6's significance rules (high confidence,
high significance, repetition, or goal-relevance). Model-free motion regions (≈0.55
confidence) intentionally stay below the threshold and don't flood the world; real
object/face detections (≥0.7) promote and are written via the resolving feed.

### Events
`vision.observation`, `vision.object.appeared`, `vision.object.disappeared`,
`vision.object.promoted`, `vision.motion.started`, `vision.motion.stopped`,
`vision.scene.changed`, `vision.entity.linked` — plus the transport `vision.camera.*`
events.

---

## 7. Scene Graph

`scene/scene_graph.py` maintains, per camera: **persistent objects** (track id → linked
`ENT_` stable id), **spatial relationships** (`left_of`/`right_of`/`above`/`below`/
`near`/`overlapping`), **camera-relative positions** (normalized 0..1), and
**world-relative positions** via an optional calibration hook (absent calibration it
returns the camera point tagged `frame="camera"`, never a fabricated 3-D guess).
**Room mapping** is a hook (`set_room_mapper`). Geometry + state only; no reasoning.

---

## 8. Visual Memory

`memory/visual_memory.py` (SQLite, per-thread WAL connections) durably stores
**significant observations**, **visual events**, per-object **sighting histories**
(trimmed per object), and **scene changes**, with retrieval by recency/camera/object.
In-memory when no path is given. Stores evidence; performs no reasoning.

---

## 9. Reliability

The Cognitive Core never crashes because of vision:

- **Camera disconnects / browser refresh / permission loss / Wi-Fi interruption** —
  transport health + reconnect (same permanent id) + recovery events.
- **Corrupted frames / packet loss** — the decoder returns `None`; the frame is flagged
  `corrupt` and dropped, never raised.
- **Processor failure** — `VisionProcessor.process()` is never-raises; the pipeline adds
  a second guard.
- **Cognition failure** — the bridge guards every collaborator call.
- **Server restart** — the persistent registry keeps camera ids.

---

## 10. Performance

Stages are separated so transport threads are never blocked by AI work:

- **transport threads** decode + enqueue (per camera);
- **one processing thread** runs the pipeline + observation building + bridge, throttled
  to `processing.max_processing_fps`;
- metrics + visualization are computed on demand.

Benchmark (`python -m core.vision.benchmark`, CPU, default pipeline): **~290 fps**,
**~3.4 ms/frame** end-to-end, detection recall 1.0 on the synthetic motion stream.

See **[M14_VISION_API.md](M14_VISION_API.md)** for the API and
**[M14_VISION_CONFIG.md](M14_VISION_CONFIG.md)** for configuration.
