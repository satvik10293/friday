# M5 — Executive Brain

> Strangler-fig, additive. No M1–M4 file modified. Five new packages:
> `core/executive/`, `core/context/`, `core/attention/`, `core/world/`,
> `core/cognition/`.
> **Test status: 198 passed** (M1 20 · M2 27 · M3 44 · M4 33 · **M5 74**).
> Imports are side-effect free.

M5 turns FRIDAY from a *goal-driven* system into a *thinking* system. Through M4
she could store goals and execute skills; now she **reasons** about goals, **builds
context**, **prioritizes** information with attention, maintains a **world model**,
and **coordinates execution** through a central **Executive Brain**.

---

## Pipeline

```
        M1            M2          M4            M5             M3          M3        M1/M3
   ┌─────────┐  ┌──────────┐  ┌────────┐  ┌──────────────┐  ┌────────┐  ┌──────────┐  ┌───────┐
   │ Runtime │→ │  Memory  │→ │ Goals  │→ │ Executive    │→ │ Skills │→ │ Security │→ │ Audit │
   └─────────┘  └──────────┘  └────────┘  │ Brain        │  └────────┘  └──────────┘  └───────┘
                                          └──────┬───────┘
                          ┌───────────────┬──────┼───────┬────────────────┐
                          ▼               ▼      ▼       ▼                ▼
                      Context Engine  Attention  Reasoner  exec Planner  Orchestrator
                          │               │                                │
                          └── World Model ┘                       (routes to SkillExecutor)

   The Cognitive Loop (M5) drives one cycle through the Brain on the Runtime scheduler:
   Observe → Context → World → Attention → Reason → Plan → Select → Execute → Reflect → Learn
```

The Executive Brain is **inserted between Goals and Skills**. It never replaces a
layer — it *coordinates* them. All execution still flows through the M3
`SkillExecutor`; all reasoning is recorded to the M1 `DecisionLog`; all learning is
stored to the M2 `MemoryService`.

---

## Packages & modules

### `core/world/` — World Model
FRIDAY's persistent internal model of reality.

| Module | Role |
|---|---|
| `entities.py` | `WorldEntity` (typed thing: user/project/runtime/system, with mutable `state` + stable `attributes`) and `WorldRelationship` (weighted directed edge). Pure data. |
| `snapshots.py` | `WorldSnapshot` + `diff_snapshots(before, after)` → `{added, removed, changed}` for change detection. |
| `world_model.py` | `WorldModel` — SQLite (`data/world.db`, per-thread conns + WAL + `schema_version`). `observe()` (merge), `update_entity`, `get_entity`, `entities_by_kind`, relationships, `snapshot`/`compare`/`restore`, `counts`, `health`. Survives restart. |

### `core/attention/` — Attention System
Decides what matters right now.

| Module | Role |
|---|---|
| `scoring.py` | Pure salience math: `recency_score` (half-life decay), `priority_score` (1=highest → 1.0), `combine` (weighted), `score_goal`/`score_memory`/`score_observation` → `AttentionScore` (with component breakdown — every score is explainable). |
| `attention.py` | `AttentionSystem` — `rank_goals`/`rank_memories`/`rank_observations`, `top`, `focus`, `metrics`, `health`. |

### `core/context/` — Context Engine
Builds the best reasoning context by composing existing layers.

| Module | Role |
|---|---|
| `context_package.py` | `ContextPackage` — memories, goals, lessons, focus items, world summary, confidence, trace id. Fully inspectable. |
| `context_builder.py` | `ContextBuilder(memory, goals, attention, world)` — `build(query)` pulls memories (M2), active goals (M4), reflections, attention focus (M5), world state (M5). Degrades gracefully when a layer is absent. |

### `core/executive/` — Executive Brain
The central cognition layer.

| Module | Role |
|---|---|
| `state.py` | `CognitiveState`/`FocusState`/`AttentionTarget`/`ActiveContext` + `CognitiveStateStore` (SQLite `data/cognition.db`, single authoritative row). Persistent + observable; focus survives restart. |
| `reasoner.py` | `Reasoner` → `ReasoningResult`. Four testable capabilities: `reason_memory` (contradictions), `reason_goals` (prioritization), `reason_dependencies` (unmet deps), `reason_conflicts` (competing active goals). Heuristic, deterministic, pluggable for an LLM later. |
| `planner.py` | Executive `Plan`/`PlanStep`/`PlanDependency`/`PlanResult` + `ExecutivePlanner`. `build_plan` (objective scaffold or explicit steps), `from_goals` (**consumes M4 goals** — goal ids → step ids, goal deps → step deps), `expand_step` (recursive nesting), short/long horizon. |
| `orchestrator.py` | `Orchestrator` — `decide` (execute/wait/blocked split), `execute_step` (routes skills through **M3 SkillExecutor**; thinking steps complete synthetically), `execute_plan` (dependency-honoring, **bounded** so a bad graph can't loop). |
| `executive.py` | `ExecutiveBrain` — `think`/`decide`/`evaluate`/`execute_plan`/`status`/`health` + `attach(runtime)`. Owns observability (DecisionLog), learning (MemoryService), events (`ExecEvent`), metrics, and cognitive-state persistence. Singleton `get_executive_brain()`. |

### `core/cognition/` — Cognitive Loop
FRIDAY's thinking cycle.

| Module | Role |
|---|---|
| `loop.py` | `CognitiveLoop` — ten phases (`CognitivePhase`): Observe → Context → World → Attention → Reason → Plan → Select → Execute → Reflect → Learn. `run_cycle()` is **one bounded pass** (never `while True`); `start()`/`stop()` are idempotent and schedule the cycle on the Runtime. Emits `CognitionEvent.CYCLE`. `auto_execute` flag gates action. |

---

## Public API (ExecutiveBrain)

```python
brain.think(query)            -> ReasoningResult   # context + attention + reason; sets focus
brain.decide(objective)       -> Plan              # reason, then plan (from goals if present)
brain.evaluate(plan)          -> dict              # feasibility/readiness/confidence
brain.execute_plan(plan)      -> PlanResult        # delegate to Orchestrator → SkillExecutor; learn
brain.status()                -> dict              # cognitive state + metrics
brain.health()                -> dict              # aggregated subsystem health
brain.attach(runtime)                              # register health providers
```

Every **mutating/cognitive** action: opens a trace → writes a `DecisionLog` row
(the *why*) → emits an `ExecEvent` on the Runtime bus (the *what*) → updates
metrics → (on execution) stores a learning memory.

---

## Integration strategy (no duplication)

| M5 needs… | Reuses (does not reimplement) |
|---|---|
| relevant memories, learning | **M2 `MemoryService`** (`recall`, `remember`) |
| goals, dependencies, status | **M4 `GoalService` / `Goal`** (`list_goals`, statuses, deps) |
| actual execution | **M3 `SkillExecutor`** (the single approved path; permissions/audit intact) |
| events, scheduling, health | **M1 `Runtime`** (`emit`, `schedule`, `register_health`) |
| the "why" of every decision | **M1 `DecisionLog`** + tracing |

`ExecEvent` and `CognitionEvent` are `str`-enums, so they're first-class bus keys
**without editing the frozen 3.0 `Signal` taxonomy** — same strangler-fig move M4
used for `GoalEvent`.

---

## Observability

Every Executive Brain decision produces a trace id, a `DecisionLog` entry, and a
reasoning summary (`rationale`). Metrics exposed via `brain.metrics()`:

- `plans_created`, `plans_completed`, `plans_failed`
- `thoughts`, `reasoning_cycles`
- `attention_evaluations`, `steps_executed`

Health providers registered through `attach(runtime)` → surfaced by
`Runtime.health()`: **executive**, **context**, **attention**, **world** (and
**cognition** once the loop starts).

---

## Tests — 74 new (198 total, no M1–M4 regressions)

| File | Count | Covers |
|---|---|---|
| `tests/test_world.py` | 11 | entity CRUD/roundtrip, observation merge, relationships, snapshot+diff, removal diff, restore, **restart recovery**, health. |
| `tests/test_attention.py` | 10 | priority/recency math, combine normalization, goal/memory component scoring, **ranking order**, focus/top, metrics. |
| `tests/test_context.py` | 7 | empty package, graceful degradation, memory pull, **active-goal inclusion**, lesson collection, world summary, health/metrics. |
| `tests/test_reasoner.py` | 10 | contradiction detection, consistency, goal ranking, priority-derived score, **dependency gaps**, conflict detection, integrated `analyze`, confidence penalty. |
| `tests/test_exec_planner.py` | 9 | objective scaffold, explicit steps, ready-step gating, **from_goals dependency mapping**, terminal-status carry, blocked steps, completion, recursive expand, dict/result. |
| `tests/test_orchestrator.py` | 7 | decide split, blocked report, synthetic execution, full plan run, **failure blocks dependents**, **real skill via SkillExecutor**, metrics. |
| `tests/test_executive.py` | 11 | think→reasoning, focus from active goal, **decide builds plan from goals**, scaffold fallback, evaluate, **execute+learn to memory**, decisions logged, **runtime event**, attach health, aggregated health, **cognitive-state restart recovery**. |
| `tests/test_cognition.py` | 9 | **all ten phases run**, planning over active goals, learning stored, metrics, auto_execute off, **idempotent start/stop**, runtime scheduling, cycle event, status shape. |

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
# expected: 198 passed
```

---

## Design decisions

- **Insert, don't replace.** The Brain sits *between* Goals and Skills and
  coordinates the existing layers. Removing it leaves M1–M4 fully functional.
- **Injected, optional dependencies + `is not None`.** Same truthiness discipline
  as M3/M4 — an empty collection-like dependency is never silently swapped for a
  global. Every subsystem is unit-testable in isolation and the Brain degrades
  gracefully when a layer is absent.
- **Explainable cognition.** Attention scores expose their components; reasoning
  carries a rationale; plans record provenance (`goal_id` per step). Nothing the
  Brain decides is a black box.
- **The loop is scheduled, never spun.** `run_cycle()` is a single bounded pass;
  `execute_plan` is bounded by `max_steps`. There is no `while True` anywhere — the
  Runtime scheduler drives cadence, and start/stop are safe and idempotent.
- **Heuristics behind seams.** Reasoner and Planner are deterministic heuristics
  today; an LLM reasoner/planner drops in behind the same interfaces with no
  call-site change. This package is explicitly "the context source for future LLM
  integration."

### One deliberate naming deviation
The spec listed `tests/test_planner.py`, but that filename already holds **M4's**
goal-planner tests. Overwriting it would delete M4 coverage (a regression the spec
forbids), so the executive-planner tests live in **`tests/test_exec_planner.py`**.
The two planners are distinct: `core/goals/planner.py` decomposes objectives into
*goal trees*; `core/executive/planner.py` turns goals/objectives into *executable
plans*.

---

## New data files (created at runtime; gitignore candidates)

```
data/world.db        # World Model; created on first WorldModel()
data/cognition.db    # Cognitive state; created on first CognitiveStateStore()
```

---

## Not yet done (next)

- **LLM reasoner + planner** behind the existing interfaces (this layer was built
  to be the context/decision substrate for exactly that).
- **Close Goals ↔ Brain wiring in the spine:** route `friday_neural` through the
  Executive Brain (needs Git installed — it edits live 3.0 code).
- **World perception:** feed the World Model from real signals (screen/vision,
  system stats, project state) instead of synthetic observations.
- **Mission Control:** surface cognitive state, the plan board, attention focus,
  and the decision feed in the HUD.
