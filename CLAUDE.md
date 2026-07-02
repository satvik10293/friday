# Friday 3.0

A local, personality-driven AI assistant. She reasons over her own accumulated
knowledge (an Obsidian vault), answers locally when she can and falls back to the
cloud when she can't, learns from what she answers, surfaces her own code-improvement
ideas for review, watches your screen to offer help, and reads/summarises PDFs.

Owner: **Satvik**.  Platform: **Windows** (CPU-only).

---

## Run

```powershell
python setup.py                 # one-time: install deps (or: pip install -r requirements.txt)
# add your API keys to friday_config.json   (Groq / Gemini / OpenAI)
python friday_spine.py             # voice mode (full boot)
python friday_app.py               # desktop UI — cinematic HUD in a native window (no browser)
python -m core.io.friday_face      # HUD backend only (localhost:7862); friday_app.py wraps it
```

The **UI** is the Friday-2.0-style cinematic HUD (WebGL neural core in the centre,
mood-tinted rails, conversation timeline, mini-brain roster, gesture overlay). It
runs as a **native desktop window** via `friday_app.py` (pywebview → Edge WebView2),
not a browser tab. Static assets live in `core/io/ui/` (`friday_ui.html/.css/.js`);
`core/io/friday_face.py` is the Flask backend (`/api/status|command|agents|job|events`,
`/gesture/*`). **Gesture control** (`core/io/friday_gesture.py`) runs on MediaPipe's
modern **HandLandmarker Tasks API** (model bundled at `core/io/models/hand_landmarker.task`;
the legacy `mp.solutions` API was removed in mediapipe ≥0.10). Gestures: fist→minimize,
open-palm→restore, call-me→launch voice mode, point→focus Friday's window, peace→scout
the screen (asks the brain), thumbs-up→approve, and pinch→system volume (pycaw). Tunable
under the `gesture` block in `friday_config.json`; a listener bridges gestures to the HUD
timeline and brain. Toggle it from the core overlay button (live webcam feed streams there).

The package `core` is **side-effect-free to import** — environment setup lives only
in `setup.py`, never in `core/__init__.py`. Run any module's CLI with `-m`, e.g.
`python -m core.brain.friday_local --ask "..."`.

---

## Architecture (`core/` subpackages)

`core/` is organized into subpackages — each row below is a real folder:

| Subpackage | Modules | Role |
|---|---|---|
| (root) | `friday_spine` | Orchestrator: boots modules, wires signals, runs the main loop |
| `core/brain/` | `friday_brain`, `friday_neural`, `friday_local`, `friday_context`, `friday_critic`, `friday_codex`, `friday_planner` | Respond pipeline; cloud LLM chain + **local reasoning QA**; code/plan specialists |
| `core/knowledge/` | `friday_world`, `friday_sovereign`, `friday_chronicle`, `friday_learning`, `friday_pdf` | Vault store + FAISS search; fact extraction; memory; preference learning; PDF→notes |
| `core/persona/` | `friday_psyche`, `friday_empath` | Identity, mood, emotional tone |
| `core/io/` | `friday_face`, `friday_action`, `friday_proactive`, `friday_visual`, `friday_notify`, `friday_phone`, `friday_whatsapp`, `orb/` (M20-rev) | Web UI; screen/desktop actions; proactive watcher; visual answers; notifications; messaging. **`orb/`** = the primary floating-orb UI: native frameless pywebview window driven only via the Runtime Event Bus (`controller`, `window`, `speech_bridge`, `state`, `events`, `config`, `ui/orb.{html,css,js}`); no AI logic in the UI. Entry: `friday_orb_app.py`. Docs: `docs/M20_ORB_UI.md`. |
| `core/agents/` | `friday_codex_agent` | 24/7 self-check → improvement proposals (human-gated) |
| `core/infra/` | `friday_signal`, `friday_scheduler`, `friday_secrets` | Async event bus; periodic tasks; `.env` secret loading |
| `core/voice/` | `friday_stt`, `friday_tts`, `friday_voice`, `friday_senses`, `friday_voice_loop`, `friday_audio`, `friday_mic_test` | STT (faster-whisper) + TTS (edge-tts) + mic loop |
| `core/audio/` (M12.1, M15) | `listener/` (continuous listening, VAD, wake, transcription), `cognition/` (`AuditoryCognition`, event detection, context reasoning, auditory memory, audio attention) | Auditory perception: speech pipeline + environmental sound understanding → `Observation`s into the World Model. Additive; perception only. Docs: `docs/M15_AUDITORY_COGNITION.md`. |
| `core/vision/` (M14) | `service` (`VisionSystem`), `transport/`, `processing/`, `observation/`, `integration/`, `scene/`, `memory/`, `mission_control`, `config` | Visual perception: camera Frames → processing plugins → `Observation`s routed through Attention→Perception→Entity Resolver→World Model; Scene Graph + Visual Memory. Perception only — no reasoning, no direct World-Model writes. Docs: `docs/M14_VISION_SYSTEM.md`. |
| `core/spatial/` (M16) | `service` (`SpatialService`), `engine`, `scene_graph`, `tracker`, `relationships`, `rooms`, `localization`, `memory`, `queries` | Spatial cognition: persistent scene graph, object tracking, spatial relationships, rooms, user localization, spatial queries — all via the service layer. Docs: `docs/M16_SPATIAL_COGNITION.md`. |
| `core/services/` (M16) | `interfaces` (Protocols), `container` (DI), `{runtime,world_model,memory,attention,vision,audio,executive,configuration,plugin,learning,emotion}_service` | Service layer: from M16 on, subsystems talk ONLY through DI services (no internal imports). |
| `core/perception/hub/` (M17) | `service` (`PerceptionService`), `hub`, `fusion`, `confidence`, `context`, `timeline`, `reasoning`, `observations` | Multimodal Perception Hub (reused by the M17-revision Coordinator). Note: distinct from M6 `core/perception/*.py`. Docs: `docs/M17_PERCEPTION_HUB.md`. |
| `core/brains/` (M17-rev, M19) | `base` (`CognitiveBrain`/`SituationReport`/bus), `{vision,audio,spatial,memory,learning,emotion,automation,runtime,executive,simulation}/` | Cognitive Brains: each owns local reasoning/state/memory, emits Situation Reports. Memory Brain owns tiered memory + Knowledge Graph; Executive Brain (M18) consumes only Unified Situations; Simulation Brain (M19) predicts/simulates/risk-scores and advises the Executive (never executes). Docs: `docs/M19_SIMULATION.md`. |
| `core/coordinator/` (M17-rev) | `service` (`CoordinatorService`), `coordinator`, `unified_situation`, `config`, `events` | Cognitive Coordinator: merges Situation Reports → Unified Situations → the only gateway to the Executive Brain. Docs: `docs/M17_COGNITIVE_ARCHITECTURE.md`. |
| `core/launcher/` (M20, RC1) | `launcher` (`Launcher`), `startup`, `health`, `platform_adapter`, `logging_config`, `first_run` (RC1), `diagnostics` (RC1) | Production launcher: OS detect → config → **first-run wizard** → deps → ordered startup → health → recover, plus a **diagnostics** screen. No cognitive logic. Entry: `friday_launch.py`. Docs: `docs/M20_DEPLOYMENT.md`, `docs/RC1_RELEASE.md`. |
| `deploy/` (M20, RC1) | `install`, `build`, `release`, `version`, `bootstrap` (RC1), `rc` (RC1), `windows/` (RC1: `install.ps1`, `uninstall.ps1`, `friday.iss`) | Installer + build/release scripts (cross-platform; secrets never embedded; verifiable packages). RC1: self-provisioning `bootstrap` (creates `.venv` on first run), `rc` orchestrator (portable package + release notes + manifest), Windows installer assets. Root entries: `Install-FRIDAY.bat`, `Launch-FRIDAY.bat`. Artifacts in gitignored `dist/`. |

### Respond pipeline (per user turn)
```
user → friday_brain.respond()
  → context (intent/tone) → neural.think_with_context()
       → retrieve from vault (FAISS) + memory + identity/mood
       → LOCAL-FIRST: friday_local reasons over her knowledge (flan-t5);
         if not confident → Groq → Gemini → OpenAI
       → visual answer (open map/news/image) if the question wants one
       → learn: save substantive cloud answers back into the vault
  → critic review → response
  → sovereign extracts facts (background)
```

---

## Knowledge & data

- **Knowledge vault (Obsidian):** `C:\VAULT\satvik` — one markdown note per fact;
  notes link to `[[Friday Knowledge]]` + topic nodes for the graph view. Override
  with env `FRIDAY_VAULT`.
- **Proposals vault (Obsidian):** `C:\VAULT\friday_proposals` — the codex agent's
  self-improvement proposals (pending → approved → applied). Override with
  `FRIDAY_PROPOSALS_VAULT`.
- **FAISS index + stats:** `core/world_data/` (binary sidecar, kept out of the vault).
- **Local QA index:** `data/local_qa.{npz,json}` — rebuild with
  `python -m core.brain.friday_local --train` after she learns new things.
- **Memory / state:** `data/chronicle.db`, `data/psyche.json`, `data/learning.jsonl`,
  `data/sovereign_stats.json`.
- **Backups:** `data/codex_backups/` (auto-backup before any approved self-edit).

---

## Conventions & gotchas

- **Config:** API keys come from the environment (gitignored `.env`, loaded by
  `core/infra/friday_secrets.py`); `friday_config.json` holds only non-secret settings.
- **Imports:** fully package-qualified, e.g. `from core.knowledge.friday_world import ...`.
  Run module CLIs with `python -m core.<subpackage>.<module>` so the package resolves.
- **Path anchors:** modules live at `core/<sub>/<file>.py`; data dirs resolve to the
  project root via `parents[2]` and `core/world_data` via `parents[1]`.
- **Local-first** only applies on the main answer path (`allow_local=True`); critic /
  codex / planner go straight to the cloud.
- **Proactive watcher** uses window-title + a cheap screen-change check (no per-frame
  OCR) and only nudges when you look stuck, with a cooldown. Tunable via
  `FRIDAY_PROACTIVE_*` env vars.

---

## Known issues / TODO

- **Security:** keys now live in a gitignored `.env` (loaded into the environment).
  Rotate them — they were exposed in plaintext historically.
- **Mobile control / WhatsApp:** deferred. Messaging is feasible (`pywhatkit`); WhatsApp
  *calling* and *answering phone calls* are not (no API).
- **Voice temp files** (`test.wav`, `friday_reply.mp3`) are written to the CWD; consider
  routing them to a temp dir.
- **`friday_mic_test`** records on import (no `__main__` guard) — don't import it casually.
