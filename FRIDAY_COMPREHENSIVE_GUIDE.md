# Friday 3.0 — Comprehensive Project Guide

**A local, personality-driven AI assistant. She reasons over her own accumulated knowledge (an Obsidian vault), answers locally when she can and falls back to the cloud when she can't, learns from what she answers, surfaces her own code-improvement ideas for review, watches your screen to offer help, and reads/summarises PDFs.**

> **Accuracy note:** This guide was written by reading the actual source files. Signatures, endpoints, config keys, and CLI flags below were verified against the code (as of 2026-06-23). Where something is described at a higher level (e.g. a module whose internals weren't fully read), it is drawn from `CLAUDE.md` and the in-code docstrings/roster and noted as such.

**Owner:** Satvik · **Platform:** Windows (CPU-only) · **Version:** 3.0

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Quick Start](#quick-start)
3. [Project Layout](#project-layout)
4. [Entry Points](#entry-points)
5. [Architecture & Subpackages](#architecture--subpackages)
6. [The Respond Pipeline](#the-respond-pipeline)
7. [Knowledge & Data](#knowledge--data)
8. [HTTP API (friday_face)](#http-api-friday_face)
9. [Gesture Control](#gesture-control)
10. [Configuration](#configuration)
11. [Conventions & Gotchas](#conventions--gotchas)
12. [Development & Debugging](#development--debugging)
13. [Known Issues & TODO](#known-issues--todo)
14. [Command Cheat Sheet](#command-cheat-sheet)

---

## Project Overview

Friday 3.0 combines:

- **Local-first reasoning** — `friday_local` retrieves relevant passages from her knowledge (embedding with `all-MiniLM-L6-v2`) and has a local generative reader (`google/flan-t5-base`) compose a fresh answer. If nothing relevant is found, it returns `None` and defers to the cloud.
- **Cloud chain** — `friday_neural` routes **Groq → Gemini → OpenAI** with an emergency fallback. No single point of failure.
- **Persistent knowledge** — markdown notes in an Obsidian vault, with FAISS semantic search and a keyword fallback.
- **Personality & mood** — `friday_psyche` tracks identity/mood; `friday_empath` handles emotional tone.
- **Self-improvement** — `friday_codex_agent` runs 24/7, proposing changes for human review.
- **Native UI** — a cinematic WebGL HUD rendered in a native desktop window (pywebview → Edge WebView2), not a browser tab.
- **Voice, gesture, and screen awareness** — STT (faster-whisper), TTS (edge-tts), MediaPipe hand gestures, and a proactive screen watcher.

**Key principle:** the `core` package is **side-effect-free to import** — environment setup lives only in `setup.py`, never in `core/__init__.py`.

---

## Quick Start

**Official installer (recommended):** run `FRIDAY-Setup-<version>-<os>-<arch>.exe` —
it identifies the OS, grades the GPU (best / good / average / entry), recommends the
best FRIDAY edition, installs (CUDA torch when the GPU earns it), and launches. Build it
with `python -m deploy.setup.build_setup`. Only Python ≥ 3.10 is required beforehand.

```powershell
# from source
python deploy/bootstrap.py      # provision an isolated .venv, then launch (any OS)
# add your API keys to .env      (GROQ_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY)
python friday_launch.py         # production launcher: ordered startup + health report
python friday_app.py            # desktop UI — cinematic HUD in a native window (no browser)
python friday_spine.py          # voice mode (full boot)
python -m core.io.friday_face   # HUD backend only (127.0.0.1:7862); friday_app.py wraps it
```

**API keys:** keys are read from environment variables first (loaded from the gitignored `.env` by `core/infra/friday_secrets.py`). `friday_config.json` is a fallback for non-secret settings (models, owner name, voice, gesture). The config currently ships with empty key fields — prefer `.env`.

---

## Project Layout

```
PythonProject1/
├── core/                       # main package (side-effect-free to import)
│   ├── brain/                  # respond pipeline & reasoning
│   ├── knowledge/              # vault, memory, learning, PDF
│   ├── persona/                # identity, mood, tone
│   ├── io/                     # UI backend, actions, watcher, gesture, notify, messaging
│   ├── agents/                 # self-improvement codex agent
│   ├── infra/                  # signal bus, scheduler, secrets
│   ├── voice/                  # STT, TTS, mic loop
│   ├── world_data/             # FAISS index + stats (binary sidecar)
│   └── io/ui/                  # friday_ui.html / .css / .js  (HUD assets)
│   └── io/models/              # hand_landmarker.task (MediaPipe bundle)
├── data/                       # runtime state & memory
│   ├── chronicle.db            # memory database (SQLite)
│   ├── psyche.json             # personality/mood state
│   ├── local_qa.{npz,json}     # local retrieval QA index
│   ├── learning.jsonl          # preference/feedback log
│   ├── sovereign_stats.json    # fact-extraction stats
│   └── codex_backups/          # auto-backups before approved self-edits
├── friday_spine.py             # orchestrator (voice mode entry point)
├── friday_app.py               # desktop UI wrapper (pywebview)
├── friday_config.json          # non-secret settings
├── setup.py                    # dependency install / environment setup
├── requirements.txt            # dependencies
├── .env / .env.example         # secrets (gitignored)
└── CLAUDE.md                   # project instructions
```

---

## Entry Points

### `friday_spine.py` — Orchestrator (voice mode)
Class `FridaySpine`. `boot()` brings up modules in order, each guarded so a failure degrades rather than crashes:

1. **Signal bus** (`core.infra.friday_signal.get_bus`) — must be first; fatal if missing.
2. **Brain** (`FridayBrain`) — fatal if missing.
3. **World** (`friday_world.start(env_interval=15, knowledge_interval=300)`) — background, non-fatal.
4. **Voice** (`FridayVoice`), **5. Action** (`FridayAction`), **6. Notify** (`FridayNotify`) — non-fatal.
7. **Signal wiring** — `THINKING_DONE → speak`, `ACTION_EXECUTE → action.execute`, `MODULE_ERROR → notify`.
8. **Scheduler** — registers a 5-minute heartbeat and starts.
9. **Codex agent** — `friday_codex_agent.start()`.
10. **Proactive watcher** — `friday_proactive.start()`.

Key methods: `respond(text) → str` (delegates to brain), `say(text, interruptible=True)` (sentence-by-sentence, interruptible via a `threading.Event`), `interrupt_speech()`, `run_voice_loop()` (blocking; listens via `FridaySenses().listen_once()`), `shutdown()`, `status()`.

`run_voice_loop` treats a `"__EXIT__"` response as a shutdown signal.

### `friday_app.py` — Desktop UI
Runs the Flask HUD backend on `127.0.0.1:7862` in a background thread (`friday_face.run_background`), waits for it to come up, warms the brain (`get_brain()`), then opens a native window via `webview.create_window(...)` (1500×920, min 960×640, background `#030608`). Picks the first free port at/after 7862 so a stale instance can't block it. Requires `pywebview` (and the Edge WebView2 runtime, which ships with Windows 11).

### `core/io/friday_face.py` — HUD backend
Flask server. Can run standalone (`python -m core.io.friday_face`) or backgrounded by `friday_app.py`. Does **not** open a browser by default (pass `open_browser=True` to `run()` if you want one).

---

## Architecture & Subpackages

Each row is a real folder under `core/`.

| Subpackage | Modules | Role |
|---|---|---|
| (root) | `friday_spine`, `friday_app` | Orchestrator + desktop UI wrapper |
| `core/brain/` | `friday_brain`, `friday_neural`, `friday_local`, `friday_context`, `friday_critic`, `friday_codex`, `friday_planner` | Respond pipeline; cloud LLM chain + local reasoning QA; code/plan specialists |
| `core/knowledge/` | `friday_world`, `friday_sovereign`, `friday_chronicle`, `friday_learning`, `friday_pdf` | Vault store + FAISS search; fact extraction; memory; preference learning; PDF→notes |
| `core/persona/` | `friday_psyche`, `friday_empath` | Identity, mood, emotional tone |
| `core/io/` | `friday_face`, `friday_action`, `friday_proactive`, `friday_visual`, `friday_notify`, `friday_phone`, `friday_whatsapp`, `friday_gesture` | UI backend; screen/desktop actions; proactive watcher; visual answers; notifications; messaging; gesture control |
| `core/agents/` | `friday_codex_agent` | 24/7 self-check → improvement proposals (human-gated) |
| `core/infra/` | `friday_signal`, `friday_scheduler`, `friday_secrets` | Async event bus; periodic tasks; `.env` secret loading |
| `core/voice/` | `friday_stt`, `friday_tts`, `friday_voice`, `friday_senses`, `friday_voice_loop`, `friday_audio`, `friday_mic_test` | STT (faster-whisper) + TTS (edge-tts) + mic loop |

### `core/brain/` details (verified)

**`friday_brain.py` — `FridayBrain`**
- `respond(user_text: str) → str` — the single entry point. Always returns a string, never raises. Note: **there is no `allow_local` argument** — local-first happens inside `friday_neural`.
- Pipeline stages inside `respond()`:
  1. emit `USER_TEXT` signal
  2. `_build_context` → `friday_context.build(user_text, prev_topic, session_len)` returns a context packet (`intent`, `priority`, `topic`, `temperature`, `max_tokens`, `route_to`, `tone`, etc.); falls back to a minimal `SimpleNamespace` packet on failure
  3. emit `THINKING_START`
  4. `_neural_think` → routes to **Codex** if `"codex" in packet.route_to`, **Planner** if `"planner" in packet.route_to`, else `friday_neural.think_with_context(...)`
  5. `_critic_check` → `friday_critic.critique_with_retry(...)`
  6. emit `THINKING_DONE`
  7. `_record_learning` → `friday_learning.record_feedback(...)`
  8. `_sovereign_extract` → `friday_sovereign.run_background(...)` (background fact extraction)
- Boot wires: psyche (`boot()`), chronicle (`start_session()`), signal bus, sovereign (`load_stats()`), learning (`get_preferences()`).
- Other methods: `greeting()`, `status()`, `end_session(summary=None)`.
- `_safe_fallback()` handles greetings/time/name/exit offline; returns `"__EXIT__"` for exit/quit/bye.
- Module-level singleton: `get_brain() → FridayBrain`.

**`friday_neural.py` — the cloud reasoner**
- Multi-API routing **Groq → Gemini → OpenAI → emergency fallback**, complexity-aware, with consensus on high-stakes queries.
- Loads secrets via `friday_secrets.load_env()`. Reads keys from env vars (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`), with `friday_config.json` as fallback for non-secret settings.
- Picks the config that actually has a key filled in (so an empty `core/friday_config.json` template can't shadow the real one).
- Public functions used elsewhere: `think_with_context(text, tone, task_type, max_tokens, temperature)`, `think(prompt, system, temperature, max_tokens)`, `clear_history()`.

**`friday_local.py` — on-device reasoning QA**
- Retrieval (`all-MiniLM-L6-v2`) + reader (`google/flan-t5-base`). `answer(q)` retrieves passages; if none clear the retrieval floor (`_RETRIEVAL_FLOOR = 0.30`, top-k = 4), returns `None` to defer to the cloud.
- Index files: `data/local_qa.npz` + `data/local_qa.json`.
- CLI: `--train` (rebuild index), `--ask "..."`, `--floor <float>`.

**`friday_codex.py` / `friday_planner.py` / `friday_critic.py`** — specialists invoked by the brain:
- Codex: `build_packet(user_text, intent, language)` → `.prompt/.system/.temperature/.max_tokens`.
- Planner: `build_plan_prompt`, `parse_plan_from_response`, `format_plan_for_display`, `register_plan`.
- Critic: `critique_with_retry(prompt, response, intent, think_fn, max_retries, max_tokens)`.

### `core/knowledge/` details (verified)

**`friday_world.py`**
- Vault: `VAULT_DIR = os.environ.get("FRIDAY_VAULT", r"C:\VAULT\satvik")`. One markdown note per managed entry, YAML-style frontmatter.
- FAISS sidecar + stats in `core/world_data/` (`WORLD_DIR`).
- `VaultStore` reads/writes notes; the user's own Obsidian notes (no `fact_id` frontmatter) are **never touched**.
- FAISS semantic search with a graceful **keyword-only fallback** when `sentence_transformers`/`faiss` aren't available. Wikipedia summaries fetched on demand — **no background download/ingest loop**.
- `start(env_interval, knowledge_interval)` / `stop()` lifecycle used by the spine.

**Other knowledge modules** (from the roster/CLAUDE.md):
- `friday_sovereign` — background fact extraction; `load_stats()`, `run_background(...)`, `get_status()`. Stats in `data/sovereign_stats.json`.
- `friday_chronicle` — memory DB (`data/chronicle.db`); `start_session()`, `end_session()`, `stats()`.
- `friday_learning` — preference learning (`data/learning.jsonl`); `get_preferences()`, `record_feedback(...)`.
- `friday_pdf` — PDF → vault notes.

### `core/io/` details
- `friday_face` — Flask HUD backend (see [HTTP API](#http-api-friday_face)).
- `friday_gesture` — MediaPipe HandLandmarker; functions used by face: `set_listener(cb)`, `start()`, `stop()`, `is_running()`, `get_latest_gesture_label()`, `get_latest_frame()`.
- `friday_proactive` — screen watcher; `start()`, `stop()`, `active_window_title()`.
- `friday_action`, `friday_visual`, `friday_notify`, `friday_phone`, `friday_whatsapp` — desktop actions, visual answers, notifications, messaging.

### `core/infra/` details
- `friday_signal` — event bus; `get_bus()`, `Signal` enum (`USER_TEXT`, `THINKING_START`, `THINKING_DONE`, `ACTION_EXECUTE`, `MODULE_ERROR`, …), `bus.on(sig, handler)`, `bus.emit_sync(sig, data, source, priority)`.
- `friday_scheduler` — `start()`, `stop()`, `every_minutes(n, fn, name)`, `task_heartbeat`, `list_jobs()`.
- `friday_secrets` — `load_env()` loads `.env` into the environment.

---

## The Respond Pipeline

```
user → friday_brain.respond(user_text)
  → emit USER_TEXT
  → context.build() → packet (intent / tone / route_to / temperature / max_tokens …)
  → emit THINKING_START
  → neural:
       if "codex"   in packet.route_to → friday_codex  → neural.think()
       elif "planner" in packet.route_to → friday_planner → neural.think()
       else → neural.think_with_context()
                 (inside neural: LOCAL-FIRST via friday_local;
                  if not confident → Groq → Gemini → OpenAI → emergency fallback)
  → critic.critique_with_retry()
  → emit THINKING_DONE
  → learning.record_feedback()                (background-ish)
  → sovereign.run_background()                 (background fact extraction)
  → return response string
```

Local-first reasoning is implemented **inside `friday_neural`/`friday_local`**, not as a flag on `brain.respond()`.

---

## Knowledge & Data

- **Knowledge vault (Obsidian):** `C:\VAULT\satvik` — one markdown note per fact. Override with env `FRIDAY_VAULT`.
- **Proposals vault (Obsidian):** `C:\VAULT\friday_proposals` — codex agent proposals (pending → approved → applied). Override with `FRIDAY_PROPOSALS_VAULT` *(per CLAUDE.md)*.
- **FAISS index + stats:** `core/world_data/` (binary sidecar, kept out of the vault).
- **Local QA index:** `data/local_qa.{npz,json}` — rebuild with `python -m core.brain.friday_local --train` after she learns new things.
- **Memory / state:** `data/chronicle.db`, `data/psyche.json`, `data/learning.jsonl`, `data/sovereign_stats.json`.
- **Backups:** `data/codex_backups/` (auto-backup before any approved self-edit).

---

## HTTP API (friday_face)

Base URL: `http://127.0.0.1:7862`. Commands run as **async jobs** — POST returns a `job_id`, then you poll `/api/job/<id>` (or listen on `/api/events`).

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/` or `/friday_ui.html` | The HUD |
| GET | `/friday_ui.css`, `/friday_ui.js` | Static assets |
| GET | `/api/status` | Full status snapshot (voice state, autonomy/mood, system battery/internet, agents roster, scheduler, gesture, memory count, recent events) |
| POST | `/api/command` | Talk to Friday. Body: `{"command": "..."}` (max 2000 chars). Returns `{"ok", "status":"running", "job_id"}` |
| POST | `/api/agents` | Deep answer with mini-brain framing. Body: `{"task": "...", "agents": ["neural","world",...]}` (agents optional). Returns a `job_id` |
| GET | `/api/job/<id>` | Poll an async job → `{"status":"running"\|"done"\|"error", "message", ...}` |
| GET | `/api/events` | SSE stream (`job_done`, `gesture`, `agents.completed`, ping keep-alives) |
| POST | `/gesture/start` | Start webcam gesture control (registers the on-gesture listener) |
| POST | `/gesture/stop` | Stop gesture control |
| GET | `/gesture/status` | `{"running": bool, "label": str}` |
| GET | `/gesture/stream` | MJPEG of the annotated webcam feed |
| — | `/chat`, `/greeting`, `/stats`, `/clear`, `/status` | Legacy endpoints (kept for compatibility) |

**Mini-brain roster** (advertised in `/api/status`): `neural`, `local`, `world` (elite); `codex`, `planner`, `critic`, `sovereign`, `visual`, `pdf` (standard). `/api/agents` auto-selects a relevant subset based on keywords in the task (code → Codex/Critic/Neural; plan → Planner/Neural/World; screen → Visual/Neural/World) unless you pass explicit `agents`.

---

## Gesture Control

`core/io/friday_gesture.py` runs on MediaPipe's modern **HandLandmarker Tasks API** (model bundled at `core/io/models/hand_landmarker.task`; the legacy `mp.solutions` API was removed in mediapipe ≥0.10). A listener bridges gestures to the HUD timeline and the brain; the `peace` gesture spawns a background "scout the screen" query grounded by the active window title.

**Gesture → action map** (from `friday_config.json`):

| Gesture | Action |
|---|---|
| fist | `minimize_all` |
| open_palm | `restore_all` |
| call_me | `launch_friday` |
| point | `focus_friday` |
| peace | `scout` (asks the brain about your screen) |
| thumbs_up | `approve` |
| rock | `media_playpause` |
| three | `screenshot` |
| ok | `approve` |

Tuning keys under `gesture`: `stable_ms` (90), `same_cooldown_ms` (650), `min_gap_ms` (120), `retrigger_on_hold` (false), plus toggles `enabled`, `window_actions`, `pinch_volume`.

---

## Configuration

### `friday_config.json` (actual shape)

```json
{
  "groq_api_key": "",
  "groq_model": "llama-3.3-70b-versatile",
  "groq_fallback_model": "llama-3.1-8b-instant",
  "gemini_api_key": "",
  "gemini_model": "gemini-2.0-flash",
  "openai_api_key": "",
  "openai_model": "gpt-4o-mini",
  "elevenlabs_api_key": "",
  "owner_name": "Satvik",
  "friday_version": "3.0",
  "voice":   { "engine": "edge-tts", "voice_id": "en-US-GuyNeural" },
  "stt":     { "model": "base", "device": "cpu", "compute_type": "int8" },
  "gesture": {
    "enabled": true,
    "window_actions": true,
    "pinch_volume": true,
    "stable_ms": 90,
    "same_cooldown_ms": 650,
    "min_gap_ms": 120,
    "retrigger_on_hold": false,
    "actions": {
      "fist": "minimize_all", "open_palm": "restore_all", "call_me": "launch_friday",
      "point": "focus_friday", "peace": "scout", "thumbs_up": "approve",
      "rock": "media_playpause", "three": "screenshot", "ok": "approve"
    }
  }
}
```

**The key fields are empty here on purpose** — put real keys in `.env`.

### Environment variables

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ELEVENLABS_API_KEY` | Provider keys (loaded from `.env`) |
| `FRIDAY_VAULT` | Knowledge vault path (default `C:\VAULT\satvik`) |
| `FRIDAY_PROPOSALS_VAULT` | Proposals vault path (per CLAUDE.md) |
| `FRIDAY_PROACTIVE_*` | Proactive watcher tuning (per CLAUDE.md) |

---

## Conventions & Gotchas

- **Config/secrets:** keys come from the environment (gitignored `.env`, loaded by `friday_secrets.load_env()`); `friday_config.json` holds only non-secret settings. Neural picks the config that actually has a key filled in.
- **Imports:** fully package-qualified, e.g. `from core.knowledge.friday_world import ...`. Run module CLIs with `python -m core.<subpackage>.<module>`.
- **Path anchors:** modules live at `core/<sub>/<file>.py`; data dirs resolve to project root via `parents[2]`, and `core/world_data` via `parents[1]`.
- **Side-effect-free imports:** environment setup lives only in `setup.py`, never in `core/__init__.py`.
- **Degraded boot:** the spine guards each module; a missing voice/action/notify degrades rather than crashes. Only the signal bus and brain are fatal.
- **`"__EXIT__"`:** the brain returns this sentinel for exit/quit/bye; the voice loop and face translate it into a graceful goodbye.
- **Proactive watcher** uses window-title + a cheap screen-change check (no per-frame OCR) and only nudges when you look stuck, with a cooldown.

---

## Development & Debugging

```powershell
# Brain self-test (uses fallback responses if no API key is set)
python -m core.brain.friday_brain

# Ask the local reasoner directly / rebuild its index
python -m core.brain.friday_local --ask "What is machine learning?"
python -m core.brain.friday_local --train

# Run the HUD backend alone (no native window)
python -m core.io.friday_face        # http://127.0.0.1:7862

# Full voice boot
python friday_spine.py
```

- `friday_brain.__main__` runs a self-test: prints the greeting, and if `groq_api_key` is empty it exercises only the offline `_safe_fallback` cases; otherwise it runs the live pipeline on a couple of prompts and prints `status()`.
- Logging: `logging.basicConfig(level=logging.INFO, ...)`; bump to `DEBUG` for more detail.

---

## Known Issues & TODO

- **Security:** keys now live in a gitignored `.env` (loaded into the environment). **Rotate them** — they were exposed in plaintext historically.
- **Mobile control / WhatsApp:** deferred. Messaging is feasible (`pywhatkit`); WhatsApp *calling* and *answering phone calls* are not (no API).
- **Voice temp files:** `test.wav` and `friday_reply.mp3` are written to the CWD (both are present in the project root). Consider routing them to a temp dir.
- **`friday_mic_test`** records on import (no `__main__` guard) — don't import it casually; run it as a module instead.

---

## Command Cheat Sheet

| Task | Command |
|---|---|
| Install deps | `python setup.py` |
| Voice mode (full boot) | `python friday_spine.py` |
| Desktop HUD window | `python friday_app.py` |
| HUD backend only | `python -m core.io.friday_face` |
| Brain self-test | `python -m core.brain.friday_brain` |
| Ask local reasoner | `python -m core.brain.friday_local --ask "..."` |
| Rebuild local QA index | `python -m core.brain.friday_local --train` |
| Override vault path | set `FRIDAY_VAULT` before launching |

---

*Verified against source on 2026-06-23 · Owner: Satvik · Platform: Windows (CPU-only)*
