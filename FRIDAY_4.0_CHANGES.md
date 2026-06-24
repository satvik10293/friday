# FRIDAY 4.0 — Changes (M1 Runtime + Observability, M2 Memory Service, M3 Skills + Security, M4 Goal Engine + Reflection, M5 Executive Brain, M6 Perception & Awareness, M7 Knowledge & Learning Core, M8 Knowledge System + Portal, M9 Personal Model & User Intelligence)

> Strangler-fig migration: **all additive**. No existing 3.0 file was modified.
> The system still boots. **Test status: 269 passed** (`python -m pytest`).
> Dev env: installed **pytest 9.1.1** into `.venv`.
> Note: Git is not installed on this machine, so this manifest stands in for a diff.

---

## M1 — Runtime + Observability spine

| Status | File | What it is |
|---|---|---|
| NEW | `core/runtime/__init__.py` | Exports `Runtime`, `get_runtime`, `start_runtime`, `stop_runtime`, `AsyncEventBus`. |
| NEW | `core/runtime/bus.py` | `AsyncEventBus` — loop-safe pub/sub. Queue created lazily **inside** the runtime loop (fixes the 3.0 dead bus). Reuses `Signal`/`Event` from `friday_signal`. `on/off`, `emit`, `start/stop`, isolated `_dispatch`, `wait_for`, `stats`. |
| NEW | `core/runtime/runtime.py` | `Runtime` — one event loop on a dedicated thread + `ThreadPoolExecutor`. `start/stop` (idempotent), `on/off`, `emit` (thread-safe via `run_coroutine_threadsafe`), `emit_async`, `wait_for`, `spawn`, `submit`, `offload`, `schedule/cancel_schedule`, `register_health`, `health()`, `metrics()`. Singleton `get_runtime()` constructs but does **not** start (side-effect-free import). |
| NEW | `core/observability/__init__.py` | Exports tracing + `DecisionLog` + logging helpers. |
| NEW | `core/observability/tracing.py` | `contextvars` trace context: `new_trace_id`, `start_trace`, `current_trace`, `get_trace_id`, `clear_trace`, `Trace(label, fields, elapsed_ms)`. |
| NEW | `core/observability/decision_log.py` | `DecisionLog` — SQLite (`data/decisions.db`, separate from chronicle), `schema_version` migration gate. `log(trace_id, intent, route, models_used, skills_invoked, goals_touched, memory_used, confidence, cost_tokens, latency_ms, outcome, rationale, was_autonomous, source)`, `by_trace`, `recent`, `stats`. Thread-safe. Makes "independence %" a logged fact. |
| NEW | `core/observability/logging_setup.py` | `configure()` + `JsonFormatter` that injects the current trace id. Not called on import. |
| NEW | `pytest.ini` | `[pytest] pythonpath=. ; testpaths=tests ; addopts=-q` |
| NEW | `tests/conftest.py` | `runtime` fixture (started `Runtime`, stopped on teardown). |
| NEW | `tests/test_runtime.py` (14 tests) | idempotent start; recovery after stop; **cross-thread emit reaches handler** (3.0 dead-bus regression); handler-failure isolation; offload-in-pool; submit future; scheduler fires (sync+async); spawn; `wait_for` + timeout; health/metrics shape; health-provider register + error containment. |
| NEW | `tests/test_observability.py` (6 tests) | trace id uniqueness; trace context roundtrip; decision roundtrip w/ JSON fields; truthful-independence signal; durable reopen; stats. |
| NEW | `docs/M1_RUNTIME_OBSERVABILITY.md` | Design doc + M2+ integration plan. |

---

## M2 — Memory Service (supersedes `friday_chronicle`; chronicle left intact)

| Status | File | What it is |
|---|---|---|
| NEW | `core/memory/__init__.py` | Exports `MemoryStore`, embedders, vector indexes, `WorkingMemory`, `MemoryService`, `get_memory_service`, `migrate_from_chronicle`, `TIERS`. |
| NEW | `core/memory/embedder.py` | `Embedder` protocol; `HashingEmbedder` (deterministic, dep-free, md5 buckets); `MiniLMEmbedder` (lazy `all-MiniLM-L6-v2`); `get_embedder()` picks best available. |
| NEW | `core/memory/index.py` | `VectorIndex` protocol; `NumpyFlatIndex` (exact cosine fallback); `FaissHNSWIndex` (`IndexIDMap2` over `IndexHNSWFlat`, inner-product = cosine, keyed by memory id); `build_index()` factory. Index is derived/rebuildable. |
| NEW | `core/memory/store.py` | `MemoryStore` — SQLite **source of truth**. Per-thread connections + WAL + `busy_timeout` (fixes shared-conn / unused-lock). One `memories` table (id, ts, session_id, role, kind, content, topic, importance, tier, embed_id, access_count, last_access, deleted, superseded_by, metadata). FTS5 search w/ triggers + LIKE fallback. `schema_version` + `imports` tables. `insert`, `mark_embedded` (writes `embed_id`), `touch`, `update_tier`, `soft_delete`, `hard_delete`, `set_superseded`, `get`, `by_ids`, `keyword_search`, `episodic_older_than` (inclusive `<=`), `iter_live`, `counts`, import bookkeeping. |
| NEW | `core/memory/working.py` | `WorkingMemory` — bounded in-RAM attention buffer (deque). |
| NEW | `core/memory/service.py` | `MemoryService` — charter API: `remember`, `recall` (+score provenance), `consolidate` (summarize old episodic → semantic, demote raw → archival), `forget` (soft/hard), `amend` (supersede + lineage), `rebuild_index` (recovery), `assemble_context`, `stats`, `health`, `attach(runtime)`. Singleton `get_memory_service()`. SQLite = truth; vectors keyed by in-row `embed_id`. |
| NEW | `core/memory/migrate.py` | `migrate_from_chronicle(service, path)` — idempotent one-way import of legacy memories/facts/preferences; re-remembers them (embedded + indexed). |
| NEW | `tests/test_memory_store.py` (8 tests) | CRUD; FTS/LIKE search + deleted exclusion; `by_ids` filter; supersede lineage; tiers + counts + invalid-tier guard; access touch; cross-thread write; imports. |
| NEW | `tests/test_memory_index.py` (5 tests) | cosine ranking; remove + size; reset + add_many; empty search; factory. |
| NEW | `tests/test_memory_service.py` (10 tests) | embed_id linkage; recall ranking + provenance; soft `forget`; hard purge; `amend` lineage + recall; `consolidate` (summary + archive, injected summarizer); `rebuild_index` recovery; keyword fallback; bounded working mem; `attach`; context budget. |
| NEW | `tests/test_memory_migrate.py` (3 tests) | imports all kinds + recallable; idempotent (no dups); no-source handling. |
| NEW | `docs/M2_MEMORY_SERVICE.md` | Design doc + defect-closure table. |
| EDIT | `core/memory/store.py` | `episodic_older_than()`: `ts < ?` → `ts <= ?` (inclusive). Fixes a coarse-clock (Windows ~15 ms `time.time()`) boundary miss in `consolidate()`. (This was within the new file; noted for completeness.) |

---

## M3 — Skills + Security foundation (the single approved execution path)

| Status | File | What it is |
|---|---|---|
| NEW | `core/skills/exceptions.py` | `SkillError` hierarchy (NotFound, Duplicate, Validation, PermissionDenied, ApprovalRejected/Timeout, PolicyViolation, SandboxTimeout, ExecutionError). |
| NEW | `core/skills/permissions.py` | `Permission` (SAFE/USER_APPROVAL/ADMIN_ONLY/SYSTEM) + `RiskLevel` + `requires_approval()`. |
| NEW | `core/skills/results.py` | `Result` / `SuccessResult` / `FailureResult`. |
| NEW | `core/skills/context.py` | `SkillContext` (trace_id, runtime, memory_service, decision_log, working_memory, user_role, caller, metadata). |
| NEW | `core/skills/manifests.py` | `SkillManifest` + `build_manifest()` (discovery/serialization). |
| NEW | `core/skills/skill.py` | Abstract `Skill` (metadata + validate/run/health/manifest; sync or async run). |
| NEW | `core/skills/registry.py` | Thread-safe `SkillRegistry` (register/unregister/get/has/list/find_by_permission, duplicate-guarded) + `get_registry()`. |
| NEW | `core/skills/audit.py` | `AuditLog` → `data/audit.db` (every execution; schema_version; survives restart). |
| NEW | `core/skills/executor.py` | `SkillExecutor` — the ONE governed pipeline: resolve→validate→policy→role→approval→sandbox→audit+decision+security+metrics+events. `execute` + async `aexecute`. |
| NEW | `core/skills/__init__.py` | Public exports (side-effect-free; security imported lazily in executor). |
| NEW | `core/skills/builtin/__init__.py` | `register_builtins()` + `ALL_BUILTIN`. |
| NEW | `core/skills/builtin/memory_search.py` | `MemorySearchSkill` (SAFE, read). |
| NEW | `core/skills/builtin/memory_store.py` | `MemoryStoreSkill` (USER_APPROVAL, write). |
| NEW | `core/skills/builtin/health_check.py` | `HealthCheckSkill` (SAFE) — runtime + memory health. |
| NEW | `core/skills/builtin/system_status.py` | `SystemStatusSkill` (SAFE) — CPU/mem (psutil optional). |
| NEW | `core/security/__init__.py` | Security layer exports (side-effect-free). |
| NEW | `core/security/roles.py` | `Role` (guest/user/admin/system) + `allows()` clearance + `get_role()`. |
| NEW | `core/security/policies.py` | `PolicyEngine` + tag-driven defaults (deny_shell_execution, deny_network_access, require_approval_for_messaging, limit_file_modification); effects ALLOW/DENY/REQUIRE_APPROVAL. |
| NEW | `core/security/approvals.py` | `ApprovalManager` (request/wait/approve/reject/list_pending, auto_decider, timeout) — UI-ready. |
| NEW | `core/security/sandbox.py` | `Sandbox`/`ThreadSandbox`/`NullSandbox` — wall-clock timeout; seam for future containers. |
| NEW | `core/security/validation.py` | `validate_args`, `sanitize_shell`, `is_safe_path`. |
| NEW | `core/security/security_log.py` | `SecurityLog` → `data/security.db` (failed approvals, permission/policy violations, suspicious). |
| NEW | `tests/test_permissions.py` (5) | permission/risk ordering; requires_approval; role×permission matrix; get_role. |
| NEW | `tests/test_skills.py` (13) | manifest; validation; builtins; registry CRUD + duplicate + missing; register_builtins/find_by_permission; idempotency. |
| NEW | `tests/test_executor.py` (9) | success; not-found; validation; role-denied+security; async skill; trace→decision-log; metrics; crash isolation; policy DENY. |
| NEW | `tests/test_approvals.py` (6) | auto-approve/reject; external approve/reject; timeout; messaging-policy approval. |
| NEW | `tests/test_audit.py` (4) | audit record/query/persist; security-log record/filter; executor writes audit. |
| NEW | `docs/M3_SKILLS_SECURITY.md` | Design doc + pipeline + coverage. |
| EDIT | `core/runtime/runtime.py` | Added `submit_coro(coro)` — schedules a coroutine on the loop and returns a result-propagating Future (used by the executor for async skills). Additive to the M1 module. |
| EDIT | `core/skills/executor.py` | `is not None` dependency checks (an empty `SkillRegistry` is falsy via `__len__`; `or` dropped the injected registry). |
| EDIT | `tests/conftest.py` | Added `memory_service` + `make_executor` fixtures. |

New runtime data files: `data/audit.db`, `data/security.db`.

The official execution pipeline is now real: **Runtime → Brain → Memory → Skills → Security → Audit.**

---

## M4 — Goal Engine + Reflection (goal-driven cognition; new package `core/goals/`)

| Status | File | What it is |
|---|---|---|
| NEW | `core/goals/__init__.py` | Public exports (side-effect-free): `Goal`, `GoalStatus`, `ReflectionRecord`, `TERMINAL_STATUSES`, `new_goal`/`validate_goal`/`is_ready`/`is_blocked`/`is_terminal`, `GoalEvent`, `GoalMetrics`, `GoalStore`, `Planner`/`GoalTree`/`default_decompose`, `ProgressEngine`, `GoalScheduler`, `ReflectionEngine`, `GoalService`, `get_goal_service`. |
| NEW | `core/goals/models.py` | Pure data: `GoalStatus` enum (PENDING/ACTIVE/BLOCKED/COMPLETED/FAILED/ARCHIVED), `TERMINAL_STATUSES`, `Goal` dataclass (`to_dict`/`to_row`/`from_row`), `ReflectionRecord`. No I/O. |
| NEW | `core/goals/goal.py` | Domain helpers: `new_goal()` (uuid id, clamped confidence), `validate_goal`, `is_ready` (all deps COMPLETED), `is_blocked` (any dep FAILED), `is_terminal`. |
| NEW | `core/goals/events.py` | `GoalEvent` **str-enum** (`goal.created/started/completed/failed/blocked/reflected`) — works directly as a runtime-bus key without touching the frozen 3.0 `Signal` enum. |
| NEW | `core/goals/metrics.py` | `GoalMetrics` counters (created/activated/completed/failed/blocked/reflected) + live `snapshot(store)`. |
| NEW | `core/goals/storage.py` | `GoalStore` — SQLite (`data/goals.db`). Per-thread connections + WAL + `busy_timeout` + `schema_version` (mirrors M2). `goals` + `goal_events` tables; CRUD, filtered `list_goals(status/owner/parent)`, `search_goals`, `counts_by_status`, append-only event history, `export_all`/`import_all`. |
| NEW | `core/goals/planner.py` | `Planner(decomposer)` → `GoalTree(root, children)`. Default heuristic: build/app/dashboard/platform/system → 6 linear phases (Research APIs→Design→Backend→Frontend→Testing→Deployment); else generic 4-phase. Decomposer injectable (LLM planner slots in behind the same interface). Resolves dependency indices → real sibling goal_ids. |
| NEW | `core/goals/progress.py` | `ProgressEngine` — `update_progress`/`mark_complete`/`mark_failed`/`mark_blocked`/`resume_goal`; **rolls completion up to the parent** (avg of children; all COMPLETED → parent COMPLETED at 100%). Records every change in `goal_events`. |
| NEW | `core/goals/scheduler.py` | `GoalScheduler.tick()` — activate ready PENDING goals, mark BLOCKED those with a FAILED dep; `next_actions` (active, priority-ordered), `ready_goals`. Pure over the store. |
| NEW | `core/goals/reflection.py` | `ReflectionEngine.generate(goal)` → `ReflectionRecord` (summary/reason/lesson/duration/skills). Heuristic reason→lesson rules (credential/timeout/dependency/scope); analyzer pluggable for an LLM later. |
| NEW | `core/goals/service.py` | `GoalService(store, memory_service, decision_log, runtime, planner)` — the public, observable API. Every mutation: store → `goal_events` row → **DecisionLog** (why) → **Runtime** `GoalEvent` → metrics. Terminal transitions + `reflect()` write to **Memory** (lessons recallable). `attach(runtime)` registers health + a periodic `goals.tick`. Singleton `get_goal_service()` (not started on import). |
| NEW | `tests/test_goals.py` (14) | model defaults/clamp/validation, row round-trip; store CRUD/filters/counts/events; service transitions, fail-with-reason, **parent progress roll-up**; memory write on completion; decision-log records actions; **runtime event emitted** (async handler); **recovery after restart**. |
| NEW | `tests/test_planner.py` (6) | build vs generic decomposition; tree wiring + parent links; **dep indices resolved to goal_ids**; first child dep-free; **custom decomposer injection**; `all_goals`. |
| NEW | `tests/test_scheduler.py` (6) | activates only dependency-free goal; **completing a dep unlocks the next**; **failed dep blocks dependent**; next-actions priority order; `ready_goals` exclusions; tick summary shape. |
| NEW | `tests/test_reflection.py` (7) | failed→credential lesson; completed summary; unknown-reason fallback; skills recorded; **service.reflect persists lesson to memory**; missing goal → None; reflected event logged in history. |
| NEW | `docs/M4_GOAL_ENGINE.md` | Design doc: architecture, goal lifecycle, persistence/recovery, design choices, coverage. |

New runtime data file: `data/goals.db`.

FRIDAY is now **goal-driven, not just prompt-driven**: she holds intentions over time,
plans toward them, schedules ready work, tracks progress, and learns from outcomes —
feeding reflections back into memory.

---

## M5 — Executive Brain (central cognition; five new packages)

Pipeline grows: **Runtime → Memory → Goals → Executive Brain → Skills → Security → Audit.**
The Brain is *inserted between* Goals and Skills — it coordinates the existing layers, never replaces them.

| Status | File | What it is |
|---|---|---|
| NEW | `core/world/__init__.py` | Exports `WorldModel`, `WorldEntity`, `WorldRelationship`, `WorldSnapshot`, `new_entity`/`new_snapshot`/`diff_snapshots`. Side-effect-free. |
| NEW | `core/world/entities.py` | `WorldEntity` (kind/name/state/attributes/confidence) + `WorldRelationship` (weighted directed edge) + `new_entity` (deterministic `kind:name` id). Pure data. |
| NEW | `core/world/snapshots.py` | `WorldSnapshot` + `diff_snapshots(before, after)` → `{added, removed, changed}` for change detection. |
| NEW | `core/world/world_model.py` | `WorldModel` — SQLite (`data/world.db`), per-thread conns + WAL + `schema_version`. `observe` (state-merge), CRUD, relationships, `snapshot`/`compare`/`restore`, `counts`, `health`. Survives restart. |
| NEW | `core/attention/__init__.py` | Exports `AttentionSystem`, `AttentionScore`, scoring fns. Side-effect-free. |
| NEW | `core/attention/scoring.py` | Pure salience math: `recency_score` (half-life decay), `priority_score` (1=highest→1.0), `combine` (weighted), `score_goal`/`score_memory`/`score_observation` → `AttentionScore` (+ component breakdown; every score explainable). |
| NEW | `core/attention/attention.py` | `AttentionSystem` — `rank_goals`/`rank_memories`/`rank_observations`, `top`, `focus`, `metrics`, `health`. |
| NEW | `core/context/__init__.py` | Exports `ContextBuilder`, `ContextPackage`. Side-effect-free. |
| NEW | `core/context/context_package.py` | `ContextPackage` — memories + goals + lessons + focus_items + world + confidence + trace id; `summary`/`is_empty`/`to_dict`. The inspectable reasoning context (future LLM input). |
| NEW | `core/context/context_builder.py` | `ContextBuilder(memory, goals, attention, world)` — `build(query)` composes M2 recall + M4 active goals + reflections + M5 attention focus + M5 world summary; coverage-weighted confidence; degrades gracefully when a layer is absent. |
| NEW | `core/executive/__init__.py` | Exports the executive surface (`ExecutiveBrain`, `Reasoner`, `ExecutivePlanner`, `Orchestrator`, `Plan*`, `CognitiveState*`, `ExecEvent`, `get_executive_brain`). Side-effect-free. |
| NEW | `core/executive/state.py` | `CognitiveState`/`FocusState`/`AttentionTarget`/`ActiveContext` + `CognitiveStateStore` (SQLite `data/cognition.db`, single authoritative row). Persistent + observable; focus survives restart. |
| NEW | `core/executive/reasoner.py` | `Reasoner` → `ReasoningResult`. Four testable capabilities: `reason_memory` (contradictions), `reason_goals` (prioritization), `reason_dependencies` (unmet deps), `reason_conflicts` (competing active goals). Deterministic; LLM-pluggable. |
| NEW | `core/executive/planner.py` | Executive `Plan`/`PlanStep`/`PlanDependency`/`PlanResult` + `ExecutivePlanner`. `build_plan` (scaffold or explicit steps), **`from_goals` (consumes M4 goals: ids→step ids, goal deps→step deps)**, `expand_step` (recursive), ready/blocked/complete logic. |
| NEW | `core/executive/orchestrator.py` | `Orchestrator` — `decide` (execute/wait/blocked split), `execute_step` (**routes skills through M3 `SkillExecutor`**; thinking steps synthetic), `execute_plan` (dependency-honoring, **bounded by `max_steps`** — no infinite loop). Logs to DecisionLog. |
| NEW | `core/executive/executive.py` | `ExecutiveBrain` — `think`/`decide`/`evaluate`/`execute_plan`/`status`/`health`/`attach`. Owns observability (DecisionLog), learning (MemoryService), events (`ExecEvent` str-enum), metrics, cognitive-state persistence. Singleton `get_executive_brain()`. |
| NEW | `core/cognition/__init__.py` | Exports `CognitiveLoop`, `CognitivePhase`, `CognitionEvent`, `CycleResult`. Side-effect-free. |
| NEW | `core/cognition/loop.py` | `CognitiveLoop` — ten phases (Observe→Context→World→Attention→Reason→Plan→Select→Execute→Reflect→Learn). `run_cycle()` = one **bounded** pass (never `while True`); `start`/`stop` idempotent + scheduled on Runtime; emits `CognitionEvent.CYCLE`; `auto_execute` gate. |
| NEW | `tests/test_world.py` (11) | entity CRUD/roundtrip, observation merge, relationships, snapshot+diff, removal diff, restore, **restart recovery**, health. |
| NEW | `tests/test_attention.py` (10) | priority/recency math, combine normalization, goal/memory scoring, **ranking order**, focus/top, metrics. |
| NEW | `tests/test_context.py` (7) | empty package, graceful degradation, memory pull, **active-goal inclusion**, lesson collection, world summary, health/metrics. |
| NEW | `tests/test_reasoner.py` (10) | contradiction detection, consistency, goal ranking, priority-derived score, **dependency gaps**, conflict detection, integrated `analyze`, confidence penalty. |
| NEW | `tests/test_exec_planner.py` (9) | scaffold, explicit steps, ready gating, **from_goals dep mapping**, terminal-status carry, blocked steps, completion, recursive expand, dict/result. |
| NEW | `tests/test_orchestrator.py` (7) | decide split, blocked report, synthetic execution, full plan run, **failure blocks dependents**, **real skill via SkillExecutor**, metrics. |
| NEW | `tests/test_executive.py` (11) | think→reasoning, focus from active goal, **decide builds plan from goals**, scaffold fallback, evaluate, **execute+learn to memory**, decisions logged, **runtime event**, attach health, aggregated health, **state restart recovery**. |
| NEW | `tests/test_cognition.py` (9) | **all ten phases run**, planning over active goals, learning stored, metrics, auto_execute off, **idempotent start/stop**, runtime scheduling, cycle event, status shape. |
| NEW | `docs/M5_EXECUTIVE_BRAIN.md` | Design doc: pipeline diagram, package map, public API, integration strategy, observability, coverage, design decisions. |
| EDIT | `tests/conftest.py` | Added `goal_service` fixture (GoalService over a temp store + memory fixture) — additive; M1–M4 fixtures unchanged. |

New runtime data files: `data/world.db`, `data/cognition.db`.

**Naming deviation (deliberate):** the spec listed `tests/test_planner.py`, but that name already holds **M4's** goal-planner tests. Overwriting it would have deleted M4 coverage (a forbidden regression), so the executive-planner tests are in **`tests/test_exec_planner.py`**. The two planners are distinct (`goals/planner.py` builds goal trees; `executive/planner.py` builds executable plans) and both are preserved.

**Defect fixed during M5:** `attention.scoring.score_memory` sliced an entity id *before* `str()` (`mem.get("id", …)[:64]`), raising `TypeError: 'int' object is not subscriptable` on integer memory ids. Fixed to `str(...)[:64]`. Caught by `test_attention` + `test_executive` before any integration.

FRIDAY is now a **thinking system**: she reasons about goals, builds context, prioritizes information with attention, maintains a world model, and coordinates execution through a central Executive Brain — all routed through the existing Runtime/Memory/Goals/Skills/Security/Observability layers.

---

## M6 — Perception & Awareness (two new packages; 100% local)

Pipeline grows at the front: **Runtime → Perception → World Model → Attention → Executive Brain → Goals → Skills → Security → Audit.**
**Completely additive — no M1–M5 file was modified.** Integration uses subclasses + an adapter (see note below).

| Status | File | What it is |
|---|---|---|
| NEW | `core/perception/__init__.py` | Side-effect-free exports (models, events, store, fusion, manager, WorldFeed, `PerceptiveBrain`, `PerceptiveCognitiveLoop`). |
| NEW | `core/perception/models.py` | `Observation` (id/timestamp/source/type/confidence/payload/metadata) + `ObservationType` (10 types), `ObservationConfidence` (bands + `level`), `ObservationSource`, `ObservationBatch`, `new_observation`. `subject()`/`value_signature()` drive dedup. |
| NEW | `core/perception/events.py` | `PerceptionEvent` str-enum: `observation.received/changed/ignored/promoted/archived`. |
| NEW | `core/perception/store.py` | `PerceptionStore` — SQLite (`data/perception.db`), per-thread conns + WAL + `schema_version`. Tables: `observations`, `observation_history`, `sensor_health`, `sensor_metrics`. Survives restart. |
| NEW | `core/perception/fusion.py` | `SensorFusion` + `FusionRule` + `noisy_or`. Corroborating observations (screen "Chrome" + process "chrome.exe") → one boosted-confidence APPLICATION "Chrome". Pluggable rules. |
| NEW | `core/perception/manager.py` | `PerceptionManager` — dedupe, merge repeats, history, **significance** (novelty·confidence·impact·goal-relevance), **promote** to world model, **archive** low-value. `focus()` bridges to M5 Attention. |
| NEW | `core/perception/health.py` | `PerceptionHealth`/`HealthStatus`/`aggregate`/`derive_status`. |
| NEW | `core/perception/world_feed.py` | `WorldFeed` — adapter so the M5 WorldModel "observes" Observation objects via its **existing** `observe()` API (no world_model.py edit). |
| NEW | `core/perception/brain.py` | `PerceptiveBrain(ExecutiveBrain)` — adds `observe`/`analyze_environment`/`current_environment`/`important_changes` (PACKAGE 8) by subclassing. Singleton `get_perceptive_brain()`. |
| NEW | `core/perception/cognition.py` | `PerceptiveCognitiveLoop(CognitiveLoop)` — adds **Observe + Fuse** as first-class phases (PACKAGE 9) by subclassing. `PERCEPTION_PHASES` (11). |
| NEW | `core/sensors/__init__.py` | Exports `Sensor`, `SensorRegistry`, `SensorManager`, `Heartbeat`, `HeartbeatMonitor`. Side-effect-free. |
| NEW | `core/sensors/base.py` | Abstract `Sensor` (name/version/type/interval; `capabilities`/`health`/`start`/`stop`/`observe`). `poll()` = error-isolated wrapper + metrics. Local-only by contract. |
| NEW | `core/sensors/registry.py` | Thread-safe `SensorRegistry` (register/unregister/get/list/health, duplicate-guarded). |
| NEW | `core/sensors/manager.py` | `SensorManager` — polls sensors, collects, optionally fuses, feeds perception, records sensor health/metrics, `attach(runtime)` for periodic polling. |
| NEW | `core/sensors/heartbeat.py` | `Heartbeat` + `HeartbeatMonitor` (`beat`/`is_stale`/`stale`). |
| NEW | `core/sensors/builtin/__init__.py` | `register_builtin_sensors()` + `ALL_BUILTIN`. |
| NEW | `core/sensors/builtin/system_sensor.py` | cpu/ram/disk/battery/uptime (psutil optional; degrades to low-confidence "unavailable"). |
| NEW | `core/sensors/builtin/time_sensor.py` | hour/day/week/month/timezone/part-of-day (stdlib, deterministic). |
| NEW | `core/sensors/builtin/process_sensor.py` | running processes, active process, started/ended changes (psutil optional); per-app observations for fusion. |
| NEW | `core/sensors/builtin/filesystem_sensor.py` | watched dirs: new/modified/deleted files (stdlib, diffs across polls). |
| NEW | `tests/test_sensors.py` (17) | base poll + **error isolation**, registry, heartbeats, manager (**poll_once feeds perception**, failing-sensor isolation), four built-ins. |
| NEW | `tests/test_perception.py` (16) | model/roundtrip/signature, confidence levels, batch, **dedupe (received/ignored/changed)**, significance, **archival**, history, **promotion**, **restart recovery**, store counts. |
| NEW | `tests/test_fusion.py` (10) | noisy-or, **screen+process→Chrome**, single-source no-fusion, entity metadata, fuse_and_merge, distinct-app separation, custom rule, name normalization, metrics. |
| NEW | `tests/test_observation_world.py` (9) | WorldFeed entity/metadata/merge, **promote by confidence / repetition / goal-relevance**, low-confidence never promotes, batch feed. |
| NEW | `tests/test_environment_reasoning.py` (10) | `observe` polls+ingests+promotes, `current_environment`, ranked `important_changes`, **`analyze_environment` reasons about reality**, **ExecutiveBrain backward-compat**, health. |
| NEW | `tests/test_cognition_perception.py` (9) | **all 11 phases (observe+fuse first)**, sensors feed world in-cycle, plan/act on goals, auto_execute off, metrics, idempotent start/stop, learning, cycle event. |
| NEW | `docs/M6_PERCEPTION_AWARENESS.md` | Design doc: pipeline, decision flow, integration strategy, success-criteria map, design decisions. |

New runtime data file: `data/perception.db`.

**Integration note (deliberate):** PACKAGE 8/9 say "ExecutiveBrain gains…" and "Expand M5 loop," but the milestone's hard rule is "No M1–M5 files may be modified." The stricter rule wins — integration is delivered via **`PerceptiveBrain(ExecutiveBrain)`**, **`PerceptiveCognitiveLoop(CognitiveLoop)`**, and the **`WorldFeed`** adapter, leaving M1–M5 pristine and all 198 prior tests passing unchanged. `tests/conftest.py` was **not** modified (M5's additive `goal_service` fixture is reused).

**No cloud dependency.** psutil is the only optional binding; every sensor degrades to a contained local result when it's absent.

FRIDAY is now a **perception-driven** thinking system: she senses system/time/process/filesystem state, tracks changes, fuses corroborating signals, promotes important facts into her world model, focuses attention on what changed, and reasons about current reality inside planning — all locally.

---

## M7 — Knowledge & Learning Core (one new package built out; vault-backed; 100% local-first)

FRIDAY now **accumulates understanding**. Where memory (M2/M3) records *what happened*, knowledge records *what is true* — distilled concepts, coding patterns, and lessons she can recall, relate, validate, consolidate, and explain. The **Obsidian vault** (Markdown) is the permanent, user-owned source of truth; `data/knowledge.db` is a rebuildable index; the vector index is a rebuildable cache.
**Completely additive — no M1–M6 file was modified.** Integration with M2 memories and M4 reflections is by composition + `promote_*` adapter hooks. The legacy 3.0 `core/knowledge/__init__.py` docstring is left untouched (consumers import the M7 submodules directly).

| Status | File | What it is |
|---|---|---|
| NEW | `core/knowledge/knowledge_models.py` | `KnowledgeEntry` (distilled understanding; serialisable; `to_row`/`from_row`/`slug`/`touch`) + `KnowledgeCategory`, `KnowledgeRelation`, `KnowledgeStatus`, `KnowledgeLink`, `ValidationReport`, `ConsolidationResult`; `slugify`, `new_knowledge`. Pure data, no I/O. |
| NEW | `core/knowledge/knowledge_store.py` | `KnowledgeStore` — SQLite source-index (`data/knowledge.db`), per-thread conns + WAL + `schema_version`. Tables: `knowledge`, `knowledge_links`, `knowledge_history`, `knowledge_metrics`. CRUD, text search, find_by_title, links, history, metrics, counts/health, export/import. |
| NEW | `core/knowledge/knowledge_graph.py` | `KnowledgeGraph` over `knowledge_links`: `related` (symmetric) + `parent`/`child` (inverse pairs); `neighbors`/`traverse` (BFS, depth-bounded)/`path` (shortest)/`explain` → `Python → Flask → Authentication`. |
| NEW | `core/knowledge/knowledge_index.py` | `KnowledgeIndex` — semantic retrieval cache. **Reuses M2 `HashingEmbedder` + `NumpyFlatIndex`/FAISS by composition**; owns a str↔int id map. `add`/`remove`/`search`/`rebuild`/`reset`/`size`/`health`. Fully rebuildable from the store. |
| NEW | `core/knowledge/knowledge_validator.py` | `KnowledgeValidator` — quality gate. Detects **duplicates**, **contradictions** (opposite polarity on a shared subject), **outdated/superseded** entries, **low confidence** → `ValidationReport` recommending `store`/`update`/`reject`. Local, deterministic. |
| NEW | `core/knowledge/learning_engine.py` | `LearningEngine` — experience → knowledge. `extract_lesson` (the *TemplateNotFound* lesson), `learn_from_memories`, `promote_memory`, `promote_reflection`. Rule-based keyword distillation + category guessing; no cloud. |
| NEW | `core/knowledge/coding_knowledge.py` | `CodingKnowledge` — curated, **distilled** patterns (Flask session auth · SQLite-per-thread · API retry/backoff · boundary error handling). `patterns`/`seed` (idempotent, keyed by title)/`find` (term-scored). |
| NEW | `core/knowledge/documentation_service.py` | `DocumentationService` — the sanctioned **last-resort** external bridge. Local-first lookup order; **injected/optional `fetcher` (None ⇒ offline by default)**; `summarize` distils to a few sentences — **never stores a whole page**; only proposes an unstored candidate. Fetcher faults never crash FRIDAY. |
| NEW | `core/knowledge/knowledge_consolidator.py` | `KnowledgeConsolidator` — clusters overlapping entries (single-link token overlap), writes one summary, **archives** the originals (never deletes), records lineage in history. |
| NEW | `core/knowledge/vault.py` | `ObsidianVault` — Markdown adapter (YAML front-matter + body + `[[links]]`). `render`/`parse`/`write`/`read`/`scan`/`changed_since`/`delete`/`health`. **Preserves manual edits** (won't clobber a newer on-disk note unless `force=True`). Default `C:\VAULT\friday_knowledge` (env `FRIDAY_KNOWLEDGE_VAULT`). |
| NEW | `core/knowledge/knowledge_service.py` | `KnowledgeService` — public API composing store/index/graph/validator/learner/coding/docs/consolidator/vault. `remember_knowledge`/`teach`/`learn`/`search_knowledge`/`answer` (local-first, external opt-in)/`promote_memory`/`promote_reflection`/`learn_from_goal`/`relate`/`explain`/`consolidate`/`archive`/`seed_coding_patterns`/`rebuild_from_vault`/`validate`/`stats`/`health`/`attach`. `KnowledgeEvent` str-enum; `get_knowledge_service()` singleton. |
| EDIT (additive) | `tests/conftest.py` | Added `knowledge_store` + `knowledge_service` fixtures (temp DB + numpy index + temp vault). No existing fixture changed. |
| NEW | `tests/test_knowledge_store.py` (16) | slugify/new_knowledge/roundtrip, CRUD, delete-cascades-links, list filters, text search, find_by_title, usage/status, links, history+metrics, counts/health, export/import, by_ids, **side-effect-free import**. |
| NEW | `tests/test_knowledge_graph.py` (10) | related symmetry, parent/child inverse, remove, filtered neighbors, BFS traverse, depth bound, shortest path, no-path, **explain title chain**, cycle-safe. |
| NEW | `tests/test_knowledge_index.py` (10) | add/search, empty, size, re-add replace, remove, remove-unknown no-op, **rebuild**, reset, health, id-map stable after remove. |
| NEW | `tests/test_learning_engine.py` (12) | extract lesson (+category guess), too-short, custom title, learn-from-memories, promote memory/reflection, validator: clean/duplicate/low-confidence/contradiction. |
| NEW | `tests/test_documentation_service.py` (8) | summarize distils (not a dump), empty, **offline by default**, **local-first skips external**, **external only when local insufficient**, no-fetcher → none, fetcher exception safe, **candidate never auto-stored**. |
| NEW | `tests/test_knowledge_consolidator.py` (7) | cluster grouping, **summary+archive+lineage**, skip singletons, coding patterns available, **seed idempotent**, find. |
| NEW | `tests/test_knowledge_service.py` (25) | remember+search, **vault note written**, teach trusted, **duplicate refines in place**, low-confidence rejected, update, learn distils, promote reflection/memory, learn_from_goal, relate+explain, **answer local-first / no-external-by-default / external opt-in**, consolidate, archive, seed patterns, validate, stats/health, **runtime event emitted**, **vault render/parse roundtrip**, **vault preserves manual edits**, vault scan, **rebuild_from_vault**, singleton. |
| NEW | `docs/M7_KNOWLEDGE_CORE.md` | Design doc: storage hierarchy (vault → db → vectors), local-first read path, module map, knowledge-vs-memory, charter compliance. |

New runtime data file: `data/knowledge.db` (rebuildable from the vault).

**Local-first, enforced in code:** `answer()` searches local knowledge first and returns `{source:'none'}` unless `allow_external=True`; only then does `DocumentationService` consult an **injected** fetcher (None/offline by default), **summarise** the result, and hand back an unstored candidate. *"Never search first. Always search last. External information must be summarised before storage. Never store entire pages."* — satisfied.

**Vault as source of truth:** every stored entry is also written as a Markdown note; the store + index rebuild from the vault (`rebuild_from_vault`), and user edits win (the vault writer refuses to overwrite a newer note unless explicitly forced).

FRIDAY now learns from her own experiences (memories → lessons), from completed goals (reflections → knowledge), and from explicit teaching — validating against what she already knows, relating concepts into a navigable graph, consolidating overlap into summaries, and keeping it all in a vault the owner can read and edit.

---

## M8 — Knowledge System + Knowledge Portal (additive files + one new package; 100% local-first)

M8 makes the M7 Knowledge Core *usable*: a unified search cascade, a distillation writer that produces clean Obsidian notes, a vault organiser, an Executive-Brain seam, and a local offline web portal ("private Wikipedia") over the whole thing.
**Completely additive — no M1–M7 file was modified.** M8 lists `knowledge_store/graph/validator/models` as deliverables, but those already exist from M7 and the hard rule forbids modifying M1–M7 files — so M8 **reuses** the M7 modules and adds only new files (`KnowledgeItem`≈M7 `KnowledgeEntry`, etc.). New files land in `core/knowledge/`; the portal is the new package `core/knowledge_portal/`.

| Status | File | What it is |
|---|---|---|
| NEW | `core/knowledge/knowledge_search.py` | `KnowledgeSearch` — unified cascade **Working Memory → Memory Service → Knowledge Store → Knowledge Graph → External**. Stops at the first tier clearing a confidence `threshold`; external only when local confidence < threshold **and** `allow_external`. `SearchResult` (tier/confidence/items/related/candidate/**trace**). |
| NEW | `core/knowledge/knowledge_writer.py` | `KnowledgeWriter` + `DistilledNote` — distils raw text into the `# Title / ## Concept / ## Example / ## Related` note format, stores it (validated, vaulted via M7), generates `[[backlinks]]`, and creates real graph relations to existing related concepts. |
| NEW | `core/knowledge/vault_manager.py` | `VaultManager` — Obsidian organisation over the M7 vault: standard folders (`Programming/ Projects/ Goals/ Reflections/ Knowledge/ Daily/`), category→folder routing, create/update notes, backlink extraction, `integrity_check()` (broken links / missing ids), stats/health. |
| NEW | `core/knowledge/executive_bridge.py` | `ExecutiveKnowledgeBridge` — M5 seam: `search_knowledge`/`store_knowledge`/`build_context`/`augment_context` (folds knowledge into a live `ContextPackage` via `world['knowledge']` + merged `lessons`). No M5 file touched. |
| NEW | `core/knowledge_portal/__init__.py` | Side-effect-free package exports; **lazy** `PortalServer` so importing never pulls in Flask. |
| NEW | `core/knowledge_portal/portal_api.py` | `PortalAPI` — framework-agnostic REST logic (plain dicts): list/get/create/update/**delete=archive**/search/graph/stats. Fully testable without a server. |
| NEW | `core/knowledge_portal/portal_graph.py` | `build_graph(store)` → `{nodes, edges}`; category colours, usage-weighted node size, symmetric `related` collapsed to one undirected edge. |
| NEW | `core/knowledge_portal/portal_ui.py` | `render_dashboard()` — one self-contained HTML page (no tabs, **no CDN**): stats, most-used, recent, live search, concept detail, and an interactive **canvas force-graph** (zoom/pan/select). |
| NEW | `core/knowledge_portal/portal_server.py` | `PortalServer` — wraps the API + UI in **Flask** (lazy import, **localhost-only** `127.0.0.1:5000`). `build_app`/`run`/`start_background`; `get_portal_server()` uses the M7 singleton. |
| NEW | `core/knowledge_portal/portal_sync.py` | `PortalSync` — durable SQLite ↔ vault reconciliation (`db_to_vault`/`vault_to_db`/`full_sync`) reusing M7 methods. Website reads the API live (no separate store). |
| NEW | `tests/test_knowledge_search.py` (8) | tier hit, working-memory priority, **no external by default**, **external last-resort opt-in**, related attached, serialisable, empty query, threshold gating. |
| NEW | `tests/test_knowledge_writer.py` (8) | note markdown format, concept extraction, related inference, structured store, **graph relation to existing**, vault note written, render, empty concept. |
| NEW | `tests/test_knowledge_validator.py` (7) | store/duplicate/low-confidence-reject/outdated-update/contradiction/confidence/serialisable (M8 quality-system contract over the M7 validator). |
| NEW | `tests/test_knowledge_system.py` (11) | VaultManager structure/routing/lesson-folder/backlinks/**broken-link integrity**/clean/stats; ExecutiveKnowledgeBridge search/store/build_context/**augments ContextPackage**. |
| NEW | `tests/test_knowledge_portal.py` (16) | PortalAPI CRUD/archive/search/stats; graph payload (+edge collapse, colours); sync db→vault & **full roundtrip**; Flask app builds + `/health//stats///knowledge/search` routes respond; **side-effect-free import**. |
| NEW | `docs/M8_KNOWLEDGE_SYSTEM.md` | Design doc: three synchronized representations, search cascade, portal, success-criteria map, additive-deviation rationale. |
| EDIT (additive) | `tests/conftest.py` | (unchanged in M8 — reuses the M7 `knowledge_store`/`knowledge_service` fixtures.) |

No new runtime data file — M8 reuses M7's `data/knowledge.db` and the Obsidian vault. The portal serves on `http://127.0.0.1:5000` (offline, localhost-only).

**Three synchronized representations:** SQLite (`data/knowledge.db`, source of truth) ↔ Obsidian vault (human-readable mirror) ← Knowledge Portal (live visual face, reads the API). `PortalSync.full_sync()` reconciles store ↔ vault; the website needs no separate store.

**Local-first preserved:** the search cascade tries all four local tiers before external, and external still obeys the M7 charter (offline by default, summarise-before-store, never a whole page, unstored candidate only).

FRIDAY can now learn, organise, link, distil, search-local-first, graph, and **reason over** her knowledge — and the owner can browse it all in a local browser that mirrors the Obsidian vault.

---

## M9 — Personal Model & User Intelligence System (one new package; local + privacy-first)

M9 turns FRIDAY from a generic assistant into a **personalized companion** that understands its primary user — profile, preferences, habits, interests, projects, communication & learning style, and approved long-term context — and uses that to personalize knowledge, prioritize goals, and **explain why**.
**Completely additive — no M1–M8 file was modified.** New package `core/user_model/`; M2/M4/M7/M8 services are *injected* (composition), never edited. **Git was installed this milestone** (`git version 2.54.0.windows.1`, via winget) — the long-standing prerequisite is now met.

| Status | File | What it is |
|---|---|---|
| NEW | `core/user_model/__init__.py` | Side-effect-free exports (models, engines, service, dashboard). DB opens only on `UserModelService()`/`get_user_model_service()`. |
| NEW | `core/user_model/models.py` | Pure data models: `UserProfile`, `Preference`, `Habit`, `Interest`/`InterestLink`, `Project`, `RelationshipFact`, `Evidence`, `UserContextPackage` + enums (`PreferenceCategory`, `ProjectStatus`, `CommunicationAspect`, `LearningStyleType`). No I/O. |
| NEW | `core/user_model/store.py` | `UserModelStore` — SQLite (`data/user_model.db`), per-thread conns + WAL + `schema_version`. 11 domain tables + `user_events` + `user_metrics`. `UserModelEvent` str-enum. Local-only. |
| NEW | `core/user_model/user_profile.py` | `ProfileManager` — the identity row with `update`/`merge`(union lists, fill-empty scalars)/`add_to`/version history/`revert`. |
| NEW | `core/user_model/preferences.py` | `PreferenceEngine` — auto-learns preferences from repeated signals (`observe` nudges score toward 1/0); `set`/`score`/`strong`. |
| NEW | `core/user_model/habits.py` | `HabitTracker` — confidence-scored patterns from **reported** activity only (coarse part-of-day buckets; no surveillance). `record_activity`/`discovered`/`typical_time`. |
| NEW | `core/user_model/interests.py` | `InterestGraph` — interest weights, symmetric links, evolution events, and `relevance_boost(text)` for personalised re-ranking. |
| NEW | `core/user_model/project_tracker.py` | `ProjectTracker` — active/paused/completed lifecycle, milestones + progress, and links to M4 goals / M7–M8 knowledge / M2 memories. |
| NEW | `core/user_model/communication_model.py` | `CommunicationModel` — four learned dials (detail/technical/structure/terminology) with labels + `adapt_hint()`. |
| NEW | `core/user_model/learning_profile.py` | `LearningProfile` — visual / step-by-step / example-driven / deep-dive; `dominant()` + distribution. |
| NEW | `core/user_model/relationship_memory.py` | `RelationshipMemory` — **approval-gated** long-term facts; `propose` (inactive) vs `remember` (approved); sensitive never auto-stored. |
| NEW | `core/user_model/personal_intelligence.py` | `PersonalIntelligence` — `build_understanding`, `suggest_knowledge` (interest/project-boosted, **explainable via `Evidence`**), `goal_relevance`/`prioritize_goals`, `personalize_response`, `explain` ("why did you recommend this?"). |
| NEW | `core/user_model/user_context.py` | `UserContextBuilder` — assembles a `UserContextPackage` (profile/goals/projects/prefs/interests/knowledge/memories) for the Executive Brain/Knowledge/Agents; `augment_context_package` folds it into an M5 `ContextPackage` (no M5 edit). |
| NEW | `core/user_model/dashboard.py` | `UserDashboard` — **data-only** widget APIs for M10 (active projects/goals, learning progress, interests, knowledge growth, comms style, personal stats). |
| NEW | `core/user_model/service.py` | `UserModelService` — facade composing all engines + injected M2/M4/M7–M8 services; `metrics`/`health`/`attach(runtime)`; `get_user_model_service()` singleton. |
| EDIT (additive) | `tests/conftest.py` | Added `user_model_store` + `user_model_service` fixtures (the latter wired to the M2/M4/M7 fixtures). No existing fixture changed. |
| NEW | `tests/test_user_profile.py` (10) | create-on-access, update/merge(union, fill-empty)/add_to, version history, **revert**, metadata merge. |
| NEW | `tests/test_preferences.py` (8) | first-signal, repeated-positive convergence, negative lowering, clamp, explicit `set`, category list, `strong`, default. |
| NEW | `tests/test_habits.py` (8) | buckets, create, **confidence growth**, discovery threshold + event, typical time, timestamp bucketing, list-by-kind. |
| NEW | `tests/test_interests.py` (8) | express/grow/clamp, link+related, self-link ignored, top ranking, **evolution events**, relevance boost. |
| NEW | `tests/test_project_tracker.py` (9) | add/idempotent, status transitions, active filter, milestones+progress, **goal/knowledge/memory links**, dedupe, find, event. |
| NEW | `tests/test_personal_intelligence.py` (16) | understanding, **interest-boosted suggestion**, no-service, **explain has evidence**, project boost, **goal prioritisation**, personalize; communication adapts (both directions); learning dominant+distribution; **relationship approval gate** (propose/remember/sensitive/reject). |
| NEW | `tests/test_user_context.py` (14) | context package (goals/projects/knowledge/conf), active goals, **approved-facts-only**, serialisable, **augment ContextPackage**; dashboard widgets/progress/knowledge-growth; service metrics/health; **local-only privacy**; **runtime event emitted**; singleton. |
| NEW | `docs/M9_PERSONAL_MODEL.md` | Design doc: what-it-learns table, architecture, personal intelligence, context builder, dashboard, **privacy guarantees**, success-criteria map. |

New runtime data file: `data/user_model.db` (local-only; never leaves the machine).

**Privacy-first, by construction:** no network code in the package; no telemetry/ads/external sharing; long-term facts are **approval-gated** and sensitive data is never auto-stored; habits come **only** from activity the user reports (coarse buckets, no surveillance); the profile is versioned, user-owned, and editable.

**Integration (additive):** interests boost M8 knowledge retrieval (interested in Python → Python knowledge ranks first, with evidence); active projects boost relevance; goals (M4) get personalised prioritisation; the `UserContextPackage` and `augment_context_package` feed the M5 Executive Brain — all by composition through injected services, no M1–M8 file touched. `UserModelEvent` is a `str`-enum bus key (no `Signal` edit), the M4/M5/M7 move again.

FRIDAY now feels like a long-term partner: she knows who Satvik is, what he's building, how he likes to be taught, and can explain every personalised recommendation with the evidence behind it.

---

## Model Storage & Git Versioning (repo initialized; configs in Git, weights out)

A standing requirement so the whole intelligence system stays **reproducible and recoverable**: Git versions every config that defines how FRIDAY thinks; model **weights never enter Git**. The repository was **initialized** this change (it wasn't one before) at the verified 500-test-green state.

| Status | File | What it is |
|---|---|---|
| INIT | `.git/` + tag `m9-baseline` | Repo initialized (`git init -b main`), local identity set, baseline commit `37dcbd7` ("M1–M9 baseline + Model Storage & Git Versioning"), tagged `m9-baseline`. 280 tracked files; tree clean. |
| EDIT (additive) | `.gitignore` | Added exclusions: model weights (`*.gguf/*.bin/*.pt/*.pth/*.safetensors/*.onnx/*.h5/*.ckpt`), all `*.db` (+`-wal/-shm`), datasets, embedding/FAISS DBs (`*.faiss/*.index`), caches, `data/core_backup_*/`, `.claude/settings.local.json`. **Exception:** the bundled `core/io/models/hand_landmarker.task` (~7 MB) stays tracked. |
| NEW | `.gitattributes` | Deterministic line endings (`* text=auto`) + binary asset rules (silences LF/CRLF churn on Windows). |
| NEW | `models/registry.json` | Machine-readable model registry (10 models: 4 llm · 2 vision · 2 speech · 2 embeddings); metadata only, `weights_in_git:false`. |
| NEW | `models/MODEL_REGISTRY.md`, `models/README.md` | Human-readable registry index + conventions. |
| NEW | `models/{llm,vision,speech,embeddings}/<name>/{metadata.json,config.yaml,README.md}` | Per-model config/metadata/docs for flan-t5, groq, gemini, openai, hand-landmarker, easyocr, faster-whisper, edge-tts, all-minilm-l6-v2, hashing. |
| NEW | `models/llm/routing.yaml` | Version-controlled brain routing rules (local-first: `flan-t5 → Groq → Gemini → OpenAI`). |
| NEW | `core/infra/model_registry.py` | `ModelRegistry` — read-only registry reader (`list_models`/`get`/`by_category`/`milestone_of`/`weights_excluded`/`config_path`/`health`); merges on-disk `metadata.json`. Side-effect-free. |
| NEW | `core/infra/repo_status.py` | `RepoStatus` — read-only Git introspection: branch/latest commit/dirty/modified files/tags, and **per-file history** (`file_added`/`file_last_modified`/`file_history`) so FRIDAY can answer "when added / modified / which commit / which milestone". Fixed read-only args (no input interpolated into commands), pathspec-safe, degrades to `{available:False}` without Git. The Mission Control "repository health" data layer. |
| NEW | `tests/test_model_registry.py` (10) | registry load/query/health, custom + missing registry, side-effect-free import. |
| NEW | `tests/test_repo_status.py` (10) | throwaway-repo branch/commit/dirty/modified, **add-vs-modify history**, milestone tags, status payload, graceful-when-not-a-repo, pathspec-not-an-option safety. |
| NEW | `docs/MODEL_STORAGE_AND_GIT.md` | The requirement: principle, in-Git-vs-excluded lists, model directory, **checkpoint convention** (commit before/after milestones; tag completions), version-history queries, Mission Control (M10) plan. |

**Git checkpoint convention (going forward):** commit before milestone work, after completion (`git commit -m "M10 complete"`), before major refactors, and after the suite is green; tag completions (`git tag -a m10-complete`). The 500-test baseline is the recovery point this protects.

**Git installed:** `git version 2.54.0.windows.1` (winget). **Tests: 500 passed** (480 + 20 new), zero regressions.

---

## Verified 3.0 defects closed

| Defect (from `FRIDAY_VERIFIED_STATE.md`) | Closed by |
|---|---|
| Event bus never started; `emit_sync` thread-fragile | M1 `Runtime` (one running loop + `emit` via `run_coroutine_threadsafe`) |
| No observability / no "why" record | M1 `DecisionLog` + tracing |
| Independence metric hardcoded `used_api=True` | M1 Decision Log makes self-vs-API a logged `route` fact |
| Brute-force `IndexFlatL2` (won't scale) | M2 FAISS HNSW (numpy fallback) |
| FAISS↔SQLite side-list desync (save-every-20) | M2 in-row `embed_id` + `rebuild_index()` |
| Shared SQLite connection; unused `_conn_lock` | M2 per-thread connections + WAL |
| No deletion/forgetting | M2 `forget` (soft/hard) + `amend` (supersede) |
| Unbounded memory growth | M2 `consolidate` (→ semantic, demote → archival) |
| No migrations | M1 + M2 + M3 `schema_version` tables |
| No tool/skill abstraction | M3 Skill base + registry + executor (every capability is a Skill) |
| `friday_action` confused-deputy risk (unauth desktop actuation) | M3 permissioned execution: role clearance + policy + approval + audit before any action |
| Actions unreachable from reasoning | M3 single execution path (`SkillExecutor.execute`) any caller can drive safely |

---

## New data files created at runtime (gitignore candidates)

```
data/decisions.db      # Decision Log; created on first get_decision_log()
data/memory.db         # Memory Service store; created on first MemoryService()
data/audit.db          # Skill execution audit; created on first SkillExecutor run
data/security.db       # Security events; created on first SecurityLog write
data/goals.db          # Goal Engine store; created on first GoalStore()/GoalService()
data/world.db          # World Model (M5); created on first WorldModel()
data/cognition.db      # Cognitive state (M5); created on first CognitiveStateStore()
data/perception.db     # Perception store (M6); created on first PerceptionStore()
data/knowledge.db      # Knowledge store/index (M7); created on first KnowledgeStore()
data/user_model.db     # Personal model (M9); created on first UserModelStore() — local-only
```

Knowledge's true source of truth is the **Obsidian vault** (`FRIDAY_KNOWLEDGE_VAULT`, default `C:\VAULT\friday_knowledge`); `data/knowledge.db` and the vector index are rebuildable from it.

---

## Not yet done (next milestones)

- **Install Git** before the rewiring step (it edits live code: `friday_neural` → Memory Service, retire dead bus + chronicle).
- **Migrate `FridayAction` (30+ commands) → permissioned Skills** and route the brain through `SkillExecutor`.
- **Mission Control** — surface `ApprovalManager.list_pending()` + audit/security/decision feeds (its own milestone).
- **Rewiring**: wire Runtime + Observability + Memory + Skills into `friday_spine` and `friday_face`; retire the dead bus and chronicle.
- **Sandbox hardening**: resource limits + process/container isolation for CRITICAL skills.

---

## How to run the tests

```powershell
.venv\Scripts\python.exe -m pytest -q
# expected: 500 passed
```

---

## M3 delivery summary (reply, verbatim)

### M3 delivered — Skills + Security Foundation

FRIDAY now has **one governed execution path for everything it does**. Built strangler-fig (additive); no 3.0 file touched. **Full suite: 91/91 passing** (M1: 20, M2: 27, M3: 44).

#### What shipped — `core/skills/` (capability) + `core/security/` (enforcement)
The complete architecture you specified, all 22 modules + 5 test files + design doc:

- **`Skill`** abstract base (metadata, permissions, risk, validate/run/health/manifest; sync **or** async)
- **`SkillRegistry`** (thread-safe, duplicate-guarded, discoverable, `find_by_permission`)
- **`SkillExecutor`** — the single pipeline: `resolve → validate → policy → role → approval → sandbox → audit + decision-log + security-log + metrics + events → structured Result`
- **Permissions** (SAFE/USER_APPROVAL/ADMIN_ONLY/SYSTEM) + **Roles** (guest/user/admin/system) with threshold clearance
- **PolicyEngine** (tag-driven: deny_shell, deny_network, require_approval_for_messaging, limit_file_modification)
- **ApprovalManager** (request/wait/approve/reject/list_pending, auto-decider, timeout — UI-ready)
- **Sandbox** (ThreadSandbox timeout now; container seam for later)
- **AuditLog** (`data/audit.db`) + **SecurityLog** (`data/security.db`) — both durable, migration-gated
- **4 reference built-in skills**: `memory.search`, `memory.store`, `system.health`, `system.status`

#### Integration with M1 + M2
- **Runtime:** async skills run via a new `Runtime.submit_coro()` (added this milestone — propagates exceptions, unlike fire-and-forget `spawn`). Lifecycle events flow through the live bus.
- **Memory:** the memory skills are the first real consumers of the M2 service — the template for all future data-touching skills.
- **Observability:** every execution gets a trace id, an audit row ("what"), a decision row ("why"), security events on violations, and metrics.

#### Two bugs the tests caught (both instructive)
1. **Truthiness trap:** `SkillRegistry.__len__` makes an empty registry *falsy*, so `self._registry = registry or get_registry()` silently dropped the injected registry. Fixed with `is not None` across all injected deps.
2. (M2 carryover context) reinforced why explicit None-checks matter for any object with `__len__`/`__bool__`.

#### The official pipeline is now real
**Runtime → Brain → Memory → Skills → Security → Audit.** Every future capability — vision, OCR, web search, automation, planning, local LLMs, autonomous agents — must flow through this, inheriting validation, permissions, approvals, sandboxing, audit, and tracing for free.

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M3_SKILLS_SECURITY.md`.

#### Recommended next
1. **Install Git** before any rewiring (it edits live 3.0 code).
2. **M4 candidates:** migrate `FridayAction` → permissioned skills + route the brain through the executor; **or** Mission Control (surface approvals + audit/security/decision feeds); **or** Goal Engine + Reflection.

---

## M4 delivery summary (reply, verbatim)

### M4 delivered — Goal Engine + Reflection

FRIDAY is now **goal-driven, not just prompt-driven**. Built strangler-fig (additive); no 3.0 file touched. **Full suite: 124/124 passing** (M1: 20, M2: 27, M3: 44, M4: 33).

#### What shipped — `core/goals/` (10 modules + 4 test files + design doc)
A clean three-layer package — pure data at the bottom, I/O in the middle, one observable orchestrator on top:

- **`Goal` model + `GoalStatus`** (PENDING/ACTIVE/BLOCKED/COMPLETED/FAILED/ARCHIVED) — pure, serializable, SQLite-round-trippable.
- **`GoalStore`** — `data/goals.db`, per-thread connections + WAL + `schema_version` (same discipline as M2). Goals **and their full event history** survive restart.
- **`Planner`** — decomposes an objective into a dependency-ordered `GoalTree`. "build a weather dashboard" → 6 linear phases (Research APIs → Design → Backend → Frontend → Testing → Deployment). The decomposer is injectable, so an LLM planner drops in behind the same interface with zero API change.
- **`GoalScheduler`** — `tick()` activates goals whose dependencies are satisfied and BLOCKS any whose dependency failed; `next_actions()` is FRIDAY's prioritized "what to do next."
- **`ProgressEngine`** — progress on a child **rolls up to its parent**; when every sub-goal completes, the parent auto-completes at 100%.
- **`ReflectionEngine`** — on a terminal goal, extracts a lesson (credential/timeout/dependency/scope heuristics now; LLM analyzer later) into a `ReflectionRecord`.
- **`GoalService`** — the single observable API. Every mutation writes the *why* (Decision Log), emits a *what* (Runtime `GoalEvent`), bumps metrics, and — on completion/failure/reflection — **persists to Memory** so lessons are recallable.

#### Integration with M1 + M2 + M3
- **Runtime:** `GoalEvent` is a `str`-enum, so it's a first-class bus key *without* editing the frozen 3.0 `Signal` taxonomy. `attach(runtime)` registers a health provider + a periodic `goals.tick`.
- **Memory:** reflections and terminal outcomes flow into the M2 service (importance-weighted, `kind="reflection"`) — the loop closes: lessons from finished goals become context for the next objective.
- **Observability:** create/plan/activate/complete/fail/block/reflect each produce a Decision Log row and a runtime event.

#### The new shape of cognition
**Goals consume memory and (next) drive skills; reflections feed memory.** FRIDAY can now hold an intention across turns and restarts, plan toward it, schedule the ready work, track it to completion, and get smarter each time.

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M4_GOAL_ENGINE.md`.

#### Recommended next
1. **Install Git** — still the gate before any rewiring that edits live 3.0 code.
2. **M5 candidates:** close **Goals → Skills** (a goal phase dispatches an M3 Skill via `SkillExecutor`); **or** route `friday_neural` through Memory + Goals (the rewiring milestone); **or** Mission Control (surface the goal board + approvals + audit/decision feeds in the HUD).

---

## M5 delivery summary (reply, verbatim)

### M5 delivered — Executive Brain

FRIDAY is now a **thinking system**, not just a goal-driven one. Built strangler-fig (additive); no M1–M4 file modified. **Full suite: 198/198 passing** (M1: 20, M2: 27, M3: 44, M4: 33, M5: 74) — comfortably past the 160+ target, zero regressions.

#### The pipeline grew one stage
**Runtime → Memory → Goals → Executive Brain → Skills → Security → Audit.** The Brain is *inserted between* Goals and Skills: it coordinates the existing layers, it does not replace any of them. Remove it and M1–M4 still run.

#### What shipped — five new packages (18 modules + 8 test files + design doc)
- **`core/executive/`** — `ExecutiveBrain` (`think`/`decide`/`evaluate`/`execute_plan`/`status`/`health`), `Reasoner` (memory/goal/dependency/conflict reasoning → `ReasoningResult`), `ExecutivePlanner` (`Plan`/`PlanStep`/`PlanDependency`/`PlanResult`; **consumes M4 goals** via `from_goals`; recursive `expand_step`), `Orchestrator` (decides what runs/waits/blocks; routes execution through the **M3 SkillExecutor**), and persistent `CognitiveState` (`data/cognition.db`).
- **`core/context/`** — the Context Engine: `ContextBuilder` assembles memories (M2) + active goals (M4) + reflections + attention focus + world state into an inspectable `ContextPackage` (the seam for future LLM integration).
- **`core/attention/`** — `AttentionSystem` ranks goals/memories/observations on importance·priority·recency·urgency; every `AttentionScore` exposes its component breakdown.
- **`core/world/`** — `WorldModel` (`data/world.db`): typed entities (user/project/runtime/system) + relationships, `observe`/`snapshot`/`compare`/`restore`. Survives restart; the seam future vision modules feed.
- **`core/cognition/`** — `CognitiveLoop`: ten phases (Observe→Context→World→Attention→Reason→Plan→Select→Execute→Reflect→Learn), **event-driven on the Runtime scheduler, never a `while True`**, idempotent start/stop.

#### Integration (reuse, no duplication)
Memories ← M2 `MemoryService`; goals/deps ← M4 `GoalService`; execution → M3 `SkillExecutor` (permissions/audit intact); events/scheduling/health ← M1 `Runtime`; the *why* of every decision → M1 `DecisionLog`. `ExecEvent`/`CognitionEvent` are `str`-enums, so they're first-class bus keys **without touching the frozen 3.0 `Signal` taxonomy** — the same move M4 used for `GoalEvent`.

#### Observability & health
Every Brain decision → trace + DecisionLog row + reasoning summary. Metrics: plans created/completed/failed, reasoning cycles, attention evaluations, steps executed. Health providers registered through `attach(runtime)`: **executive, context, attention, world** (and **cognition** when the loop runs), all surfaced by `Runtime.health()`.

#### Defect fixed
`attention.scoring.score_memory` sliced an id *before* `str()` → `TypeError` on integer memory ids. Fixed to `str(...)[:64]`; caught by the attention + executive tests before any integration ran.

#### One deliberate deviation
The spec listed `tests/test_planner.py`, but that file already holds **M4's** goal-planner tests. Overwriting it would have deleted M4 coverage (a forbidden regression), so the executive-planner tests live in **`tests/test_exec_planner.py`**. The two planners are distinct and both are preserved.

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M5_EXECUTIVE_BRAIN.md`.

#### Recommended next
1. **Install Git** before any rewiring that edits live 3.0 code.
2. **M6 candidates:** drop an **LLM reasoner/planner** behind the existing interfaces (this layer was built to be its context/decision substrate); **or** route `friday_neural` through the Executive Brain; **or** feed the World Model from real perception (screen/vision/system stats); **or** Mission Control over cognitive state + plan board + decision feed.

---

## M6 delivery summary (reply, verbatim)

### M6 delivered — Perception & Awareness Layer

FRIDAY is now a **perception-driven** thinking system, not just a goal-driven one. **Completely additive — no M1–M5 file modified.** **Full suite: 269/269 passing** (M1: 20, M2: 27, M3: 44, M4: 33, M5: 74, M6: 71) — past the 70+ target, zero regressions. 100% local; no cloud, no external AI model.

#### The pipeline grew at the front
**Runtime → Perception → World Model → Attention → Executive Brain → Goals → Skills → Security → Audit.** Sensors feed perception; perception promotes important facts into the M5 World Model; attention and the brain consume the result. Execution still flows through the M3 SkillExecutor.

#### What shipped — two new packages (19 modules + 6 test files + design doc)
- **`core/perception/`** — `Observation` model (10 types) + `PerceptionStore` (`data/perception.db`, survives restart) + `PerceptionManager` (**dedupe / merge / significance / promote / archive**) + `SensorFusion` (noisy-or; screen "Chrome" + process "chrome.exe" → one boosted APPLICATION "Chrome") + `WorldFeed` (adapter onto the existing world API) + `PerceptiveBrain`/`PerceptiveCognitiveLoop`.
- **`core/sensors/`** — abstract `Sensor` (error-isolated `poll`), thread-safe `SensorRegistry`, `SensorManager` (polls → fuses → feeds perception), `HeartbeatMonitor`, and **four built-in sensors**: system (cpu/ram/disk/battery/uptime), time, process, filesystem — all local, psutil optional.

#### Integration (additive; subclass + adapter)
PACKAGE 8/9 ("ExecutiveBrain gains…", "Expand the M5 loop") conflict with the hard rule "No M1–M5 files may be modified." **The stricter rule wins:** integration is delivered by **`PerceptiveBrain(ExecutiveBrain)`** (adds `observe`/`analyze_environment`/`current_environment`/`important_changes`), **`PerceptiveCognitiveLoop(CognitiveLoop)`** (adds **Observe + Fuse** as first-class phases — 11 total), and the **`WorldFeed`** adapter (so the world model "observes" Observation objects via its existing `observe()`). M1–M5 stay pristine; all 198 prior tests pass unchanged.

#### What FRIDAY can now do (all success criteria met, locally)
Observe system state · track changes · fuse multi-sensor observations · promote important facts (high confidence / high significance / repeated / goal-relevant) · update the world model · focus attention on observations · reason about current conditions (`analyze_environment`) · use real-world observations inside planning (`PerceptiveCognitiveLoop`).

#### Observability & persistence
`PerceptionEvent` (`observation.received/changed/ignored/promoted/archived`) is a `str`-enum bus key (no `Signal` edit). `data/perception.db` stores observations + history + sensor health/metrics, migration-gated, surviving restart. Health providers for perception + sensors surface via `Runtime.health()`.

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M6_PERCEPTION_AWARENESS.md`.

#### Recommended next
1. **Install Git** before any rewiring that edits live 3.0 code.
2. **M7 candidates:** real **screen/vision/audio sensors** feeding the SCREEN/VISION/AUDIO observation types (fusion already anticipates screen↔process corroboration); **or** LLM-backed `analyze_environment` (its ContextPackage is LLM-ready); **or** wire perception into `friday_spine`/`friday_proactive` for continuous live sensing; **or** Mission Control over the observation stream + promotions + sensor health.

---

## M7 delivery summary (reply, verbatim)

### M7 delivered — Knowledge & Learning Core

FRIDAY now has a mind that **accumulates understanding**. Where memory records *what happened*, knowledge records *what is true*. **Completely additive — no M1–M6 file modified.** **Full suite: 357/357 passing** (M1: 20, M2: 27, M3: 44, M4: 33, M5: 74, M6: 71, M7: 88) — past the 70+ target, zero regressions. 100% local-first; external knowledge is the *last* resort and is always summarised before storage.

#### The storage hierarchy — vault is the source of truth
**Obsidian vault (Markdown notes) → `data/knowledge.db` (SQLite index) → vector index (numpy/FAISS cache).** The two lower layers are fully rebuildable from the vault (`rebuild_from_vault()` re-reads the notes; the index re-embeds from SQLite). The owner can read and edit notes by hand, and **user edits win** — the vault writer refuses to overwrite a newer on-disk note unless explicitly forced.

#### What shipped — `core/knowledge/` (11 new modules + 7 test files + design doc)
- **`knowledge_models` / `knowledge_store`** — `KnowledgeEntry` (distilled understanding) over SQLite (`data/knowledge.db`): per-thread conns + WAL + `schema_version`; CRUD, text search, links, history, metrics, export/import.
- **`knowledge_graph`** — relationships: `related` (symmetric) + `parent`/`child` (inverse pairs); `traverse`/`path`/`explain` (`Python → Flask → Authentication`).
- **`knowledge_index`** — semantic retrieval that **reuses the M2 embedder + vector index by composition** (str↔int id map; `add`/`remove`/`search`/`rebuild`), rebuildable from the store.
- **`knowledge_validator`** — quality gate before storage: duplicates, contradictions, outdated/superseded, low confidence → `store`/`update`/`reject`.
- **`learning_engine`** — experience → knowledge: `extract_lesson`, `promote_memory`, `promote_reflection` (the *TemplateNotFound* lesson). Local, rule-based.
- **`coding_knowledge`** — curated, *distilled* patterns (Flask auth · SQLite-per-thread · retry/backoff · error handling); idempotent `seed`.
- **`documentation_service`** — the only sanctioned external bridge, deliberately last-resort: local-first order, **injected/optional fetcher (offline by default)**, **summarise before store, never a whole page**, only proposes an unstored candidate.
- **`knowledge_consolidator`** — clusters overlap → one summary, **archives** originals (never deletes), records lineage.
- **`vault`** — `ObsidianVault` Markdown adapter (front-matter + body + `[[links]]`): render/parse/write/read/scan/changed_since; preserves manual edits.
- **`knowledge_service`** — the public API tying it together: `remember_knowledge`/`teach`/`learn`/`search_knowledge`/`answer`/`relate`/`explain`/`consolidate`/`archive`/`rebuild_from_vault`/`stats`/`health`/`attach`. `KnowledgeEvent` str-enum bus keys; `get_knowledge_service()` singleton.

#### Local-first, enforced in code
`answer()` searches local knowledge first and returns `{source:'none'}` unless the caller passes `allow_external=True`; only then does the documentation bridge consult an injected fetcher (None/offline by default), **summarise**, and return a candidate for validation. *"Never search first. Always search last. External information must be summarised before storage. Never store entire pages."* — satisfied.

#### Additive integration (no M1–M6 edit)
Memories (M2/M3) and goal reflections (M4) become knowledge through `promote_memory`/`promote_reflection`/`learn_from_goal` — composition + adapter hooks, not edits to those modules. `tests/conftest.py` gained two fixtures (additive only). `KnowledgeEvent` is a `str`-enum, so it's a first-class bus key without touching the frozen 3.0 `Signal` taxonomy — the M4/M5/M6 move again.

#### Observability & persistence
Every mutating action records `knowledge_history` + a metric and emits a `KnowledgeEvent` (`knowledge.created/updated/learned/consolidated/archived/retrieved`) on the M1 runtime bus. `attach(runtime)` registers a health probe and schedules periodic consolidation. `data/knowledge.db` is migration-gated and survives restart; the vault is the durable, human-owned record above it.

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M7_KNOWLEDGE_CORE.md`.

#### Recommended next
1. **Install Git** before any rewiring that edits live 3.0 code.
2. **M8 candidates:** wire the Knowledge Core into the **respond pipeline** (knowledge-first answers before the cloud chain, learning substantive answers back into the vault — the 3.0 `friday_world`/`friday_learning` role, now governed); **or** an LLM-backed `summarize`/`extract_lesson` behind the existing local interfaces; **or** real `DocumentationService` fetchers (web/docs) gated by the M3 permission system; **or** Mission Control over the knowledge graph + consolidation + vault sync.

---

## M8 delivery summary (reply, verbatim)

### M8 delivered — Knowledge System + Knowledge Portal

The M7 Knowledge Core is now a **usable knowledge-driven system**, with a local website as its visual face. **Completely additive — no M1–M7 file modified.** **Full suite: 407/407 passing** (M1: 20, M2: 27, M3: 44, M4: 33, M5: 74, M6: 71, M7: 88, M8: 50) — zero regressions. 100% local-first; the portal runs entirely offline.

#### The spec overlapped M7 — additive interpretation
M8 lists `knowledge_store/graph/validator/models` as deliverables, but those already exist from M7 and the hard rule is *"Do not modify M1–M7 files."* The stricter rule wins: M8 **reuses** the M7 modules and adds only new files (`KnowledgeItem`≈`KnowledgeEntry`; `KnowledgeRelation`/`Source`/`Confidence` map onto M7 models). New files go in `core/knowledge/`; the portal is the new package `core/knowledge_portal/`.

#### What shipped — 4 new knowledge modules + a 5-module portal package + 5 test files + design doc
- **`knowledge_search`** — the unified cascade **Working Memory → Memory Service → Knowledge Store → Knowledge Graph → External**, stopping at the first tier that clears a confidence threshold; external only when local confidence is below threshold **and** explicitly allowed. Full `trace` of tiers consulted.
- **`knowledge_writer`** — distils raw text into the `# Title / ## Concept / ## Example / ## Related` note, stores it validated + vaulted, auto-generates `[[backlinks]]`, and links to existing related concepts in the graph.
- **`vault_manager`** — Obsidian organisation: the standard folder skeleton (Programming/Projects/Goals/Reflections/Knowledge/Daily), category→folder routing, backlink extraction, and an integrity check for broken links / missing ids.
- **`executive_bridge`** — the M5 seam: search/store knowledge and **fold it into a live `ContextPackage`** (`world['knowledge']` + merged `lessons`) so the Executive Brain reasons with knowledge — without editing any M5 file.
- **`core/knowledge_portal/`** — a local **"private Wikipedia"**: framework-agnostic `PortalAPI` (CRUD + search + graph + stats), `portal_graph` (nodes/edges payload), a single self-contained offline `portal_ui` dashboard with an interactive canvas force-graph (zoom/pan/select), a localhost-only Flask `PortalServer` (`127.0.0.1:5000`, lazy Flask import), and `PortalSync` (durable SQLite ↔ vault reconciliation).

#### Three synchronized representations
**SQLite (`data/knowledge.db`, source of truth) ↔ Obsidian vault (human-readable mirror) ← Portal website (live visual face, reads the API).** `PortalSync.full_sync()` reconciles store ↔ vault; the website keeps no store of its own. All three stay consistent.

#### Local-first & offline, preserved
The cascade exhausts all four local tiers before external; external still obeys the M7 charter (offline by default, summarise-before-store, never a whole page, unstored candidate only). The portal has no CDN/cloud dependency — UI assets are inlined, Flask binds to localhost, and importing the package never pulls in Flask.

#### Observability
Writes/learns/retrievals flow through the M7 `KnowledgeService`, so `KnowledgeEvent`s + metrics + history continue. The portal exposes `stats()`/`health()`; `VaultManager.health()` reports vault integrity; `PortalSync.health()` reports store/vault counts.

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M8_KNOWLEDGE_SYSTEM.md`.

#### Recommended next
1. **Install Git** before any rewiring that edits live 3.0 code.
2. **M9 candidates:** wire `ExecutiveKnowledgeBridge` into the real respond pipeline (knowledge-augmented reasoning end-to-end); **or** auto-publish learned knowledge to the portal + push notifications on new concepts; **or** real `DocumentationService` fetchers (Python/library docs, Wikipedia) gated by the M3 permission system; **or** fold the portal into the desktop HUD as FRIDAY's knowledge face.

---

## M9 delivery summary (reply, verbatim)

### M9 delivered — Personal Model & User Intelligence System

FRIDAY now **understands its primary user** and personalizes accordingly — and can explain every personalization decision. **Completely additive — no M1–M8 file modified.** **Full suite: 480/480 passing** (M1: 20, M2: 27, M3: 44, M4: 33, M5: 74, M6: 71, M7: 88, M8: 50, M9: 73) — zero regressions. 100% local, privacy-first. **Git is now installed** (`git version 2.54.0.windows.1`), closing the long-standing prerequisite.

#### What shipped — one new package `core/user_model/` (15 modules + 7 test files + design doc)
- **Identity & engines:** `ProfileManager` (versioned profile with merge/history/revert), `PreferenceEngine` (auto-learns from repeated signals), `HabitTracker` (confidence-scored patterns from **reported** activity only — no surveillance), `InterestGraph` (weights + links + evolution + relevance boost), `ProjectTracker` (lifecycle + milestones + links to goals/knowledge/memories), `CommunicationModel` (four adaptable dials), `LearningProfile` (visual/step/example/deep-dive), `RelationshipMemory` (**approval-gated** long-term facts).
- **`PersonalIntelligence`** — builds user understanding, re-ranks M8 knowledge by interests + active projects, prioritises M4 goals, and is **explainable**: every recommendation carries `Evidence`, so FRIDAY can answer *"Why did you recommend this?"* with the actual signals.
- **`UserContextBuilder`** — assembles a `UserContextPackage` (profile/goals/projects/preferences/interests/knowledge/memories) for the Executive Brain, Knowledge System, and Agent Team; `augment_context_package` folds it into an M5 `ContextPackage` without editing M5.
- **`UserDashboard`** — data-only widget APIs prepared for M10 Mission Control.
- **`UserModelService`** — facade over `data/user_model.db` (per-thread conns + WAL + schema_version), composing all engines + injected M2/M4/M7–M8 services; metrics + health + runtime events.

#### Privacy-first, by construction
No network code anywhere in the package; no telemetry, ads, or external sharing; all state in a local SQLite file the user owns. Long-term relationship facts are inactive until approved; sensitive data is never auto-stored; habit detection consumes only activity the user explicitly reports (coarse part-of-day buckets, no clock/screen watching).

#### Integration (additive)
Interests boost knowledge retrieval (interested in Python → Python knowledge ranks first, with evidence); active projects boost relevance; M4 goals get personalised prioritisation; the user context feeds the M5 brain — all by composition through injected services, no M1–M8 file touched. `UserModelEvent` is a `str`-enum bus key (no `Signal` edit).

All changes are appended to `FRIDAY_4.0_CHANGES.md` and detailed in `docs/M9_PERSONAL_MODEL.md`.

#### Recommended next
1. **Git is installed** — a repo can now be initialised (`git init` + a `.gitignore` for `data/*.db`, the vault, and `.venv`) to start version-controlling the M1–M9 build before any 3.0 rewiring.
2. **M10 candidates:** **Mission Control** (render the M9 dashboard widgets + M8 portal + goal board + decision/audit feeds in the HUD); **or** wire `UserContextBuilder` into the real respond pipeline so every answer is personalised end-to-end; **or** an Agent Team that consumes the `UserContextPackage`.
