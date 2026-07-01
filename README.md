# FRIDAY

A local-first, privacy-respecting **Cognitive Operating System** — a long-running desktop
AI companion that perceives its environment (vision, audio, space), reasons over its own
accumulated knowledge, and acts on your behalf. Everything runs on your machine; external
LLMs are an optional fallback, not a dependency.

> Owner: **Satvik** · Platform: **Windows** (CPU-first; cross-platform core) · License:
> private / all rights reserved.

---

## Quick start

```bash
# Install (RC1) ──────────────────────────────────────────────────────────────
Install-FRIDAY.bat              # Windows: full installer (copy + venv + shortcuts)
python deploy/bootstrap.py      # any OS: provision an isolated .venv, then launch
# ── or set up manually ──
python -m deploy.install        # one-time installer (deps, config, optional Groq key)
# (or: python setup.py)         # install dependencies only

# Run ────────────────────────────────────────────────────────────────────────
Launch-FRIDAY.bat               # Windows: start via the provisioned venv
python friday_launch.py         # production launcher: ordered startup + health report
python friday_orb.py            # minimal floating-orb launcher (click to start)
python friday_app.py            # desktop HUD (native window)
python friday_spine.py          # full voice-mode boot

# Operate ────────────────────────────────────────────────────────────────────
python -m core.launcher.first_run     # first-run wizard (devices + key + config)
python -m core.launcher.diagnostics   # diagnostics screen (--gui / --json)
python -m deploy.rc                    # build the Release Candidate into dist/
python -m pytest -q                    # run the test suite
```

The first **installable** build is **Release Candidate 1** (`0.20.0-rc1`) — see
`docs/RC1_RELEASE.md`. FRIDAY ships as source + a self-provisioning bootstrap (it creates
its own `.venv` on first run); a native `Setup.exe` can be compiled via
`deploy/windows/friday.iss` (Inno Setup). The **floating orb** (`friday_orb.py`) is a tiny,
always-on-top launcher (pure stdlib Tkinter, cross-platform): drag it anywhere, click to
launch FRIDAY, right-click for a menu.

---

## Architecture

FRIDAY is a society of specialized **Cognitive Brains**, each owning local reasoning,
state, and memory, and emitting structured **Situation Reports**. A **Cognitive
Coordinator** merges those into **Unified Situations** and feeds the **Executive Brain**
(the CEO). All cross-subsystem communication goes through a dependency-injected **service
layer** — no subsystem imports another's internals.

```
 Vision ┐
 Audio  ┼─ Cognitive Brains ─► Situation Reports ─► Cognitive Coordinator ─► Unified
 Spatial┘   (+ Memory, Learning, Emotion,                                     Situations
             Automation, Runtime)                                                │
                                                                                 ▼
                                                                         Executive Brain
                                                                          (decisions only)
```

| Layer | Packages | Role |
|---|---|---|
| Runtime & observability | `core/runtime`, `core/observability` | event bus, scheduler, health, tracing |
| Memory & knowledge | `core/memory`, `core/knowledge`, `core/brains/memory` | tiered memory, knowledge graph, vault |
| Cognition | `core/executive`, `core/cognition`, `core/cognition_core`, `core/attention`, `core/world` | reasoning, world model, entities/beliefs |
| Perception | `core/vision` (M14), `core/audio` (M15), `core/spatial` (M16), `core/perception` | visual / auditory / spatial perception |
| Hub & coordination | `core/perception/hub` (M17), `core/coordinator` (M17-rev) | multimodal fusion, situation coordination |
| Services | `core/services` (M16) | dependency-injected service interfaces |
| I/O & UI | `core/io`, `core/mission_control`, `friday_app.py`, `friday_orb.py` | HUD, cockpit, launcher |
| Voice | `core/voice` | STT (faster-whisper) + TTS (edge-tts) |

The package `core` is **side-effect-free to import** (no I/O, no threads, no model loads
at import). Detailed design docs live in `docs/` (`M1`…`M17`) and
`FRIDAY_4.0_CHANGES.md`.

---

## Conventions

- **Secrets** live in a gitignored `.env` (loaded by `core/infra/friday_secrets.py`);
  `friday_config.json` holds only non-secret settings.
- **Data** (`data/*.db`), **model weights**, and `.venv/` are gitignored — never committed.
- **Imports** are fully package-qualified; run module CLIs with `python -m core.<pkg>.<mod>`.
- Every milestone ships architecture + code + tests + benchmarks + docs.

---

## Testing & quality

`python -m pytest -q` — **1,100+ tests** across the runtime, memory, cognition, perception
(vision/audio/spatial), service layer, and cognitive-brain society. Each subsystem is
independently testable, side-effect-free to import, never-raises on the hot path, and
degrades gracefully when an optional backend is absent.

See `docs/PRODUCTION_AUDIT.md` for the latest production-readiness audit.
