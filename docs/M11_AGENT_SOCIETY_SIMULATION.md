# M11 — Distributed Agent Society + Cognitive Simulation + Interactive Cognitive Space

> **Tests: 651 passed** (586 M10 baseline + **65 new**). Zero regressions. 100% additive.

---

## Overview

M11 delivers three interlocking milestones that transform FRIDAY from a *thinking* system into a *distributed, self-simulating* one:

1. **Agent Society** (`core/society/`) — a living hierarchy that solves problems through coordinated parallel work.
2. **Cognitive Simulation** (`core/simulation/`) — FRIDAY simulates solutions *before* recommending them, in a fully isolated sandbox.
3. **Interactive Cognitive Space** (`core/cognitive_space/`) — a navigable 3D universe of FRIDAY's mind, with six zoom levels, LOD budgets, global search, and a server.

---

## Part 1 — Distributed Agent Society (`core/society/`)

### Hierarchy

```
Executive Brain (decides, never works)
  └─ Passive Brain Coordinator (spawns / schedules / monitors / merges / destroys)
       ├─ Research Leader    → Scientific Researcher, API Researcher
       ├─ Coding Leader      → Python Debugger, Architecture Reviewer
       ├─ Planning Leader    → Dependency Analyzer, Math Solver
       ├─ Knowledge Leader   → Documentation Writer
       ├─ Security Leader    → Architecture Reviewer
       ├─ Creative Leader    → Documentation Writer
       ├─ Automation Leader  → Dependency Analyzer
       └─ Simulation Leader  → Simulation Evaluator
            └─ (disposable workers — created per task, destroyed on completion)
```

### Modules

| Module | Role |
|---|---|
| `models.py` | `Task`, `SubTask`, `WorkerResult`, `TaskResult`, `Message`, `AgentRecord`, status enums. Pure data. |
| `store.py` | `SocietyStore` — SQLite (`data/society.db`): agent roster, lifecycle events, task history, reputation. Per-thread conns + WAL + `schema_version`. |
| `bus.py` | `AgentBus` — every message hops through `passive_brain`. `deliver_direct` between two non-coordinator agents raises `DirectMessageError` (mesh forbidden). |
| `reputation.py` | `ReputationSystem` — EWMA scoring per worker template: accuracy, reliability, speed, efficiency, success_rate → composite 0..1 `score`. Preferred templates (≥ threshold) surface first. |
| `scheduler.py` | `AgentScheduler` — parallel dispatch via `ThreadPoolExecutor` (bounded by `max_parallel`), backed by the M10 `ProcessAgentRuntime`. Resolves target names to picklable functions. |
| `workers.py` | `WorkerTemplate` catalogue: 8 templates bound to `worker_tasks` functions + domain. |
| `worker_tasks.py` | Picklable worker functions — `math_solve`, `analyze_dependencies`, `review_architecture`, `debug_python`, `research_summarize`, `api_research`, `write_documentation`, `evaluate_simulation`. Pure, side-effect-free, cross-process-safe on Windows `spawn`. |
| `leaders.py` | 8 permanent `LeaderAgent` subclasses. `plan(task) → [(template, args, kwargs)]`. `select_leader` picks by explicit domain, then keyword match, then falls back to Research. |
| `coordinator.py` | `PassiveBrainCoordinator` — owns the full lifecycle: decompose → spawn → parallel work → validate → merge → destroy → reputation update. Single relay for all communication. |
| `society.py` | `AgentSociety` facade: `solve(description)` runs the full hierarchy in one call. `prioritize`/`approve` are the Executive's gate. `status()`, `health()`, `get_society()` singleton. |

### Invariants

- Workers **never spawn workers** — structurally impossible (worker_tasks imports no coordinator or scheduler).
- All inter-agent messages relay through `passive_brain` — the bus enforces this with `DirectMessageError`.
- Workers are destroyed after every task; the active-workers count returns to zero.
- Reputation persists across restarts (`data/society.db`).

---

## Part 2 — Cognitive Simulation Engine (`core/simulation/`)

### Philosophy

> "Observe → analyze → **simulate** → evaluate → present" — FRIDAY does not answer a hard question immediately; she builds a scenario, runs it in a sandboxed virtual world, and returns a recommendation backed by simulated evidence.

### Modules

| Module | Role |
|---|---|
| `models.py` | `Simulation`, `Scenario`, `SimStep`, `SimResult`, `Recommendation`, `SimulationType` (10 types), `SimStatus`, `VirtualAgent/Goal/Knowledge/Task`. Pure data. |
| `sandbox.py` | `SimulationSandbox` — self-contained in-memory world. Admits only virtual types; production-like objects (anything with `conn`, `store`, `remember`, etc.) raise `SandboxViolation`. `assert_isolated()` sanity-checks on every run. |
| `scenario.py` | `ScenarioBuilder` — `from_problem(question)` keyword-maps to a `SimulationType`; `build(type, params)` for explicit construction. |
| `engine.py` | `SimulationEngine` — stepwise execution: agent-society stress test (analytic failure model; bounded representative sample for visualisation) and generic improvement-curve. Snapshots every step for scrubbing. |
| `director.py` | `SimulationDirector` — `direct(problem)` = one-shot problem → recommendation pipeline. |
| `controls.py` | `SimulationControls` — pause/resume/fast-forward/rewind/goto/replay over recorded steps. |
| `timeline.py` | `Timeline` — past/present/predicted-future; linear extrapolation of metric trends. |
| `service.py` | `SimulationService` — create/run/simulate/fork/compare/replay; persists metadata to `data/simulation.db`; virtual worlds stay in memory. `get_simulation_service()` singleton. |

### Agent-society stress test

The marquee scenario: given `target_agents` and `capacity`, the engine analytically models failure and latency across `steps` ramp phases, identifies the failure threshold, applies an optimisation (scale capacity to 110% of target), and calls `evaluate_simulation` from the worker library. LOD: at most `_SAMPLE_CAP = 2000` virtual agents materialised in the sandbox regardless of `target_agents`.

### Sandbox isolation guarantee

Virtual entities (`VirtualAgent`, `VirtualGoal`, `VirtualKnowledge`, `VirtualTask`) are plain dataclasses with no `store`, `conn`, or production method. The `_PROD_MARKERS` guard checks every insertion; `assert_isolated()` checks every attribute on the sandbox itself. A simulation can never read or modify real databases, goals, memories, knowledge, or user data — by construction.

---

## Part 3 — Interactive Cognitive Space (`core/cognitive_space/`)

### Six zoom levels

| Level | Name | Budget | What's visible |
|---|---|---|---|
| 1 | UNIVERSE | 64 | All of FRIDAY: goals, knowledge, projects, agents, models, simulations |
| 2 | DOMAIN | 256 | Knowledge categories, agent teams, goal status clusters |
| 3 | TEAM | 512 | Leader + their worker templates |
| 4 | AGENT | 1024 | Individual leaders + reputation-scored workers |
| 5 | TASK | 2048 | Lifecycle events (spawned/destroyed) |
| 6 | THOUGHT\_CHAIN | 256 | Simulation steps as a reasoning chain |

### Modules

| Module | Role |
|---|---|
| `models.py` | `SpaceNode`, `SpaceEdge`, `ZoomLevel`, `VisualKind`, `VISUAL_LANGUAGE` (kind → visual + colour). |
| `zoom.py` | `LEVEL_BUDGETS`, `apply_budget`, `place` (Fibonacci-sphere layout), `partition` (cells³ spatial grid for LOD culling). |
| `space.py` | `CognitiveSpaceBuilder` — one method per zoom level; resilient (`safe_call` per subsystem). |
| `search.py` | `GlobalSearch` — knowledge / goals / projects / agents / simulations / models; each hit carries a `focus` (level + node_id) for camera fly-to. |
| `service.py` | `CognitiveSpace` facade: `build(level, focus)`, `universe()`, `search(query)`, `zoom_levels()`, `visual_language()`, `health()`. `get_cognitive_space()` singleton. |
| `ui.py` | `render_cognitive_ui()` — self-contained HTML/CSS/JS page; Three.js 3D (sphere meshes + line edges, orbit/zoom), 2D canvas fallback; search → camera focus; sim timeline + controls; inspect panel; visual-language legend. Offline. |
| `server.py` | `CognitiveSpaceServer` — authenticated Flask server (`127.0.0.1:5060`): `GET /`, `/static/three.module.js`, `/api/space`, `/api/space/levels`, `/api/space/search`, `/api/space/health`, `/api/sim/<sid>/timeline`, `POST /api/sim/<sid>/<action>` (write → auth required). M10 security headers on every response. |

### Visual language

| Kind | Symbol | Colour |
|---|---|---|
| knowledge | ★ star | `#4da3ff` |
| goal / project | ◎ attractor | `#ffcc55` / `#37d39b` |
| leader / worker | ◆ entity | `#d36cff` / `#8a6cff` |
| task | ⚡ energy | `#ff8a5c` |
| decision | ✦ convergence | `#ff5d6c` |
| simulation | ◯ universe | `#5cf2e0` |
| model / domain | ○ node | `#9e9e9e` / `#6fa8ff` |

### Scalability design (Part 12)

`place(index, count)` lays nodes on a Fibonacci sphere — deterministic and stable (camera focus + partitioning both rely on it). `partition(nodes, cells)` buckets into a `cells³` grid for frustum culling. Per-level budgets cap what the server sends; the grid caps what the client traces. `test_scales_toward_100k_without_redesign` validates 100k nodes partition correctly and the task-level budget still trims to 2048. No redesign needed to scale the data layer.

---

## Tests (65 new)

| File | Tests | Coverage |
|---|---|---|
| `test_agent_lifecycle.py` | 10 | 8 permanent leaders, worker catalogue, full spawn/destroy lifecycle, leader selection (domain + keyword), merged results, worker cannot spawn workers, only leaders create workers, communication through passive brain, direct-message forbidden, status/health |
| `test_agent_reputation.py` | 7 | first record creates score, success beats failure, speed affects score, success_rate tracking, preferred threshold, top_templates ranking, persistence |
| `test_agent_scheduler.py` | 7 | single dispatch, parallel dispatch (order preserved), empty batch, unknown target graceful, failure isolated among successes, metrics collected, real-process dispatch |
| `test_cognitive_space.py` | 9 | universe level structure, all 6 levels build, visual language on nodes, visual language mapping, global search focuses, search across domains, thought chain from simulation, resilient to missing services, partition present |
| `test_simulation_engine.py` | 9 | 10 simulation types, agent-society scale simulation, generic simulation, create-then-run, controls playback, timeline past/present/future, fork, compare, persistence/health |
| `test_simulation_sandbox.py` | 7 | isolated by default, rejects production knowledge service, rejects db-conn objects, only virtual types admitted, all virtual entities admitted, real services unaffected, bulk spawn |
| `test_virtual_agents.py` | 6 | virtual agent defaults, engine populates virtual world, failures marked in virtual world, generic sim creates virtual goals/tasks, independent worlds per simulation, virtual entities never leak to production |
| `test_zoom_levels.py` | 9 | six levels, every level has budget, universe budget smallest, apply_budget trims, place is deterministic, place spreads nodes, partition buckets nodes, partition accepts dicts, scales toward 100k without redesign |

---

## Integration points (additive only — no M1–M10 file modified)

- **`core/agent_runtime`** (M10): `AgentScheduler` wraps `ProcessAgentRuntime`; workers run in separate processes with fallback.
- **`core/mission_control/resilience`** (M10): `safe_call` wraps every subsystem access in both `CognitiveSpaceBuilder` and `GlobalSearch`.
- **`core/security/auth`** (M10): `CognitiveSpaceServer` reuses M10 `Authenticator` and `security_headers` — no write without auth.
- **M7 `KnowledgeService`** / **M4 `GoalService`** / **M9 `UserModelService`** / **M6 society**: injected into `CognitiveSpace` and `GlobalSearch` — none edited.
- **`core/society/worker_tasks`**: reused directly by `SimulationEngine._run_agent_society` (`evaluate_simulation`) — consistent with the existing worker catalogue.

---

## New runtime data file

```
data/society.db     — agent roster, lifecycle, task history, reputation (local-only)
data/simulation.db  — simulation metadata (virtual worlds stay in memory)
```

Both follow the full FRIDAY store discipline: per-thread connections, WAL, `schema_version`.
