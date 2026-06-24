# MediaPipe HandLandmarker (vision/gesture)

Drives FRIDAY's gesture control via the modern MediaPipe **HandLandmarker Tasks
API** (the legacy `mp.solutions` API was removed in mediapipe ≥0.10). Used by
`core.io.friday_gesture`.

- **Weights:** `core/io/models/hand_landmarker.task` — the **one tracked weight**
  (~7 MB), bundled because the app needs it to boot. All *other* `.task` files are
  gitignored.
- **Config:** `config.yaml` (gesture→action map). **Milestone:** 3.0.
