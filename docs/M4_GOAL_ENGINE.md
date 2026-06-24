# M4 — Goal Engine + Reflection

> Strangler-fig, additive. No 3.0 file modified. New package: `core/goals/`.
> **Tests: 124 passing** (M1 20 · M2 27 · M3 44 · M4 33). Import is side-effect free.

FRIDAY can now hold **intentions over time**, not just answer turns. She takes an
objective, decomposes it into a dependency-ordered plan, schedules the ready work,
tracks progress as sub-goals complete, and — when a goal reaches a terminal state —
**reflects** and writes the lesson back into long-term memory so the next attempt
is better informed.

This is the first layer that makes FRIDAY *goal-driven* rather than *prompt-driven*.

---

## Why this milestone

M1 gave her a running nervous system (Runtime + bus + observability). M2 gave her a
real memory. M3 gave her a single governed way to *act* (Skills + Security). M4 gives
her a reason to act and a way to learn from acting: **goals are first-class, persistent,
observable, and recoverable.**

The pipeline grows one stage:

```
Runtime → Brain → Memory → Skills → Security → Audit
                      ▲                              │
                      └──────── Goals ◀──────────────┘
        (goals consume memory + drive skills; reflections feed memory)
```

---

## Architecture — `core/goals/`

Pure data and domain logic at the bottom, I/O in the middle, one observable
orchestrator on top. Every engine is constructed over an injected `GoalStore`, so
each is unit-testable in isolation.

| Module | Role |
|---|---|
| `models.py` | Pure data: `GoalStatus` (PENDING/ACTIVE/BLOCKED/COMPLETED/FAILED/ARCHIVED), `Goal` dataclass (+ `to_dict`/`to_row`/`from_row`), `ReflectionRecord`, `TERMINAL_STATUSES`. No I/O. |
| `goal.py` | Domain helpers over the models: `new_goal()` factory (uuid id, clamped confidence), `validate_goal`, `is_ready` (all deps COMPLETED), `is_blocked` (any dep FAILED), `is_terminal`. |
| `events.py` | `GoalEvent` str-enum (`goal.created/started/completed/failed/blocked/reflected`) — usable directly as a runtime-bus key without touching the legacy `Signal` enum. |
| `metrics.py` | `GoalMetrics` counters + live `snapshot(store)`. |
| `storage.py` | `GoalStore` — SQLite persistence (`data/goals.db`). Per-thread connections + WAL + `busy_timeout` + `schema_version` (mirrors M2 discipline). `goals` + `goal_events` tables; full CRUD, filtered `list_goals`, `search_goals`, `counts_by_status`, append-only event history, `export_all`/`import_all`. |
| `planner.py` | `Planner(decomposer)` → `GoalTree(root, children)`. Default heuristic recognises "build/app/dashboard/platform/system" objectives → 6 linear phases (Research APIs → Design → Backend → Frontend → Testing → Deployment); else a generic 4-phase plan. Decomposer is injectable so an LLM planner slots in behind the same interface. |
| `progress.py` | `ProgressEngine` — mutate completion/state and **roll progress up to the parent** (avg of children; all children COMPLETED → parent COMPLETED). Records every change in `goal_events`. |
| `scheduler.py` | `GoalScheduler.tick()` — activate PENDING goals whose deps are satisfied, mark BLOCKED any whose dep FAILED. `next_actions` (active, priority-ordered) and `ready_goals`. Pure over the store. |
| `reflection.py` | `ReflectionEngine.generate(goal)` → `ReflectionRecord` (summary, reason, lesson, duration, skills). Heuristic reason→lesson rules (credential/timeout/dependency/scope); analyzer is pluggable for an LLM later. |
| `service.py` | `GoalService` — the public, observable API. Owns all side-effects. |

---

## `GoalService` — the observable orchestrator

`GoalService(store, memory_service, decision_log, runtime, planner)` — every
dependency is injected and optional, so the service runs standalone in tests and
fully wired in production.

Every **mutating** action follows the same discipline:

> mutate store → append a `goal_events` row → write a **DecisionLog** entry (the
> *why*) → emit a **Runtime** `GoalEvent` (so the HUD/other subsystems react) →
> bump **metrics**.

Terminal transitions additionally write to **memory**: `complete_goal` /
`fail_goal` persist a memory, and `reflect()` persists the extracted *lesson*
(importance 0.8, `kind="reflection"`) so it surfaces on later recall
("what failed recently?", "what did I learn about API integrations?").

Surface:

- **create / plan** — `create_goal(...)`, `plan(objective)` (decompose + persist tree, return root)
- **lifecycle** — `activate_goal`, `pause_goal`, `complete_goal`, `fail_goal`, `block_goal`, `resume_goal`, `update_progress`
- **reflection** — `reflect(goal_id)` → `ReflectionRecord` (+ memory write)
- **scheduling** — `tick()` (one pass; emits started/blocked events), `next_actions(limit)`
- **queries** — `get_goal`, `list_goals(status)`, `search_goals`, `recall(query)`
- **diagnostics** — `status()`, `health()`, `metrics()`
- **wiring** — `attach(runtime, tick_every_s=30)` registers a health provider and a periodic `goals.tick` on the Runtime scheduler

Singleton: `get_goal_service()` (constructs lazily; **not** started on import).

---

## Lifecycle of a goal

```
plan("build a weather dashboard")
  └─ root (PENDING)
       ├─ Research APIs        (PENDING, no deps)
       ├─ Design Architecture  (PENDING, dep: Research APIs)
       ├─ Build Backend        (dep: Design)
       ├─ Build Frontend       (dep: Backend)
       ├─ Testing              (dep: Frontend)
       └─ Deployment           (dep: Testing)

tick()        → activates "Research APIs" (only dependency-free phase)
complete(...) → progress rolls up to root; next tick activates "Design"
fail(...)     → dependents become BLOCKED; resume_goal() re-opens them
… all children COMPLETED → root auto-COMPLETED at 100%
reflect(root) → lesson written to memory
```

---

## Persistence & recovery

`data/goals.db` is the source of truth. Goals and their full event history survive
restart: constructing a fresh `GoalStore`/`GoalService` over the same file recovers
every goal and its progress (covered by `test_goals_survive_restart`). The vector/
memory side is unaffected — reflections live in the Memory Service, themselves
rebuildable from M2's store.

---

## Tests (33)

| File | Covers |
|---|---|
| `tests/test_goals.py` | model defaults/clamp/validation, row round-trip; store CRUD, list filters, status counts, event history; service create/transitions, fail-with-reason, **parent progress roll-up**; memory write on completion; decision-log records actions; **runtime event emitted** (async handler); **recovery after restart**. |
| `tests/test_planner.py` | build vs generic decomposition; tree wiring (parent links); **dependency indices resolved to real goal_ids**; first child has no deps; **custom decomposer injection**; `GoalTree.all_goals`. |
| `tests/test_scheduler.py` | activates only dependency-free goal; **completing a dep unlocks the next**; **failed dep blocks dependent**; next-actions priority order; `ready_goals` exclusions; tick summary shape. |
| `tests/test_reflection.py` | failed→credential lesson; completed summary; unknown-reason fallback; skills recorded; **service.reflect persists the lesson to memory**; missing goal → None; reflection logged in event history. |

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
# expected: 124 passed
```

---

## Design choices worth calling out

- **str-enum events, not a new Signal value.** `GoalEvent` is a `str, Enum`, so it
  works as a bus key immediately without editing the frozen 3.0 `Signal` taxonomy —
  pure strangler-fig.
- **Injected, optional dependencies + `is not None` checks.** Same truthiness
  discipline as M3: an empty collection-like dependency must never be silently
  replaced by a global singleton. `GoalService` treats `None` (not falsiness) as
  "not provided".
- **Pure engines over a shared store.** Planner/Scheduler/Progress/Reflection hold
  no side-effects of their own; the *service* owns observability and memory. That
  keeps each engine trivially testable and lets the service stay the single
  audit point.
- **Reflection feeds memory, memory informs planning.** The loop is closed: lessons
  from finished goals become recallable context for the next objective.

---

## Not yet done (future)

- **LLM-backed decomposer & reflection analyzer** behind the existing interfaces
  (no API change required).
- **Goal-aware brain routing**: let `friday_neural` consult `next_actions()` and
  open/advance goals from conversation (needs the rewiring milestone + Git).
- **Skill execution from goals**: a goal phase that dispatches an M3 Skill via
  `SkillExecutor`, closing Goals → Skills.
- **Mission Control surface** for the goal board (active/blocked/next-actions) in
  the HUD.
