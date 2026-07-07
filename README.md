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
`deploy/windows/friday.iss` (Inno Setup). The installed app uses the standard launcher
and keeps the heavy runtime Python-source based for reliability.

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
| I/O & UI | `core/io`, `core/mission_control`, `friday_app.py`, `friday_launch.py` | HUD, cockpit, launcher |
| Voice | `core/voice` | STT (faster-whisper) + TTS (edge-tts) |

The package `core` is **side-effect-free to import** (no I/O, no threads, no model loads
at import). Detailed design docs live in `docs/` (`M1`…`M17`) and
`FRIDAY_4.0_CHANGES.md`.

---

## Roadmap — FRIDAY 5.x

Full document (canonical plan): [`docs/FRIDAY_5X_ROADMAP.md`](docs/FRIDAY_5X_ROADMAP.md) ·
cognitive-systems spec: [`docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md`](docs/FRIDAY_5X_COGNITIVE_EVOLUTION.md).

> **Prime rule — cognition is internal and totally local.** All reasoning, planning,
> simulation, memory retrieval, verification, and decision-making are internal FRIDAY
> subsystems running on this machine. The production path makes no external LLM calls;
> when local reasoning is not confident, FRIDAY thinks harder locally (a deeper
> collaborative pass) or asks for clarification — she never outsources cognition.

**Vision:** an artificial cognitive system, not a chatbot — perceive → think internally
(memory → attention → reasoning → simulation → decision) → act through governed skills →
observe → learn, with the Executive Brain as the single decision-maker and the LLM
eventually reduced to a language generator.

**Baseline:** the 4.0/5.x architecture (runtime, memory service, skills + security,
goals, executive, brains, coordinator, cognition loop, world/user models) is already
built in `core/`. The remaining work is integration and proof, not construction — so
each phase below is gated by explicit **exit criteria**, and no phase starts while the
previous one's criteria fail.

| Phase | Focus | Exit criteria (summary) |
|---|---|---|
| **A — Cutover & Consolidation** *(current)* | One boot path: `friday_launch.py` becomes the single entry (`start_runtime=True`); voice turns flow through the Master Cognition Loop; retire the 3.0 pipeline and its known defects | One entry point; mic → perception → cognition loop → executive → skill/answer → TTS with a DecisionLog row per turn; no 3.0 brain modules on the boot path |
| **B — Verification Net** *(parallel with A; blocks all later phases)* | Restore the test suite from git history; add launcher smoke + end-to-end cognition-cycle tests; add a boot/RAM/latency benchmark script | `pytest` green; baseline performance numbers recorded in the repo |
| **C — One Memory** | Migrate `chronicle.db` + vault + `local_qa` into the M2 MemoryService (episodic/semantic/procedural via existing `kind`/`tier`); wire decay/reinforcement; retrieval mandatory before reasoning | Old stores read-only; recall spot-checked; every cycle logs the memories it used |
| **D — Internal Mind** | The only large new build: Thought Generator / internal monologue, Self Model (aggregated from health/observability), autonomous goal generation (human-gated) | Inspectable thoughts between turns; Self Model answers "what can't I do and why"; one self-generated goal completes end-to-end |
| **E — Executive Supremacy & Skills** | Convert FridayAction's 30+ commands into registered Skills behind the M3 security pipeline; Simulation Brain consulted for uncertain/high-impact decisions | Every side-effecting action in `audit.db` with a DecisionLog trace; no direct action calls |
| **F — Live Models** | World / User / Self models continuously fed by the Perception Hub and injected into the Executive's context each cycle | "What's happening right now?" answered from the models, not the LLM |
| **G — Learning Flywheel** | observe → reflect → lesson → memory → behavior on the Runtime scheduler (never blocking); independence % measured truthfully from DecisionLog | Independence rises measurably over a week; lessons visible in the knowledge graph |
| **H — Performance & Local Intelligence** | Profile boot/RAM; lazy-load via ModelRegistry; tiered local stack (small quantized local reasoner + cloud fallback) | Cold boot < 10 s · simple voice reply < 700 ms · ≥ 50% of turns fully local at equal quality |
| **I — Research Track** *(unscheduled)* | Emotion modeling, curiosity, multi-agent debate, robotics, home automation | Each item enters only through a phase with its own exit criteria |

**Immediate order:** P0 = Phase A cutover + Phase B verification net · P1 = memory
migration, attention + working memory, internal thought stream · P2 = executive skill
routing, simulation gating · P3 = Self/User/World models live, learning flywheel ·
P4 = local reasoning stack.

**Cross-cutting rules:** cognition is internal (prime rule above); the Runtime owns every
singleton; all communication goes through the event bus; nothing bypasses the Executive;
memory retrieval precedes reasoning; learning never blocks a response; every phase lands
with tests, observability, and a milestone commit + tag.

**Top risks:** dual-path drift while both boot paths exist (why Phase A is first),
testless regressions (why Phase B blocks everything), RAM exhaustion from eager model
loading, and data loss during the memory migration (back up `data/` first).

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
