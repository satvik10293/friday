# FRIDAY 6.0 — Architecture Reconciliation & M13 Plan

> Chief-AI-Architect assessment. Maps the FRIDAY 6.0 "Cognitive Operating System"
> charter (20 frozen architectural decisions) against the existing, stable
> **M1–M12.1 codebase (823 tests passing)**, and scopes the next milestone. This is a
> **planning document** — no code is changed by it; M13 is not implemented until the
> design forks below are confirmed.

## Context

The FRIDAY 6.0 charter reframes the project as a **Cognitive Operating System** with
the **World Model at the center** (not the LLM). Before building anything, the
charter, the existing architecture, and the 20 frozen decisions were reconciled.

**Key finding: the charter does not require a redesign.** ~13 of the 20 decisions are
already PRESENT or substantially built, and built the way the charter wants — World
Model central, LLM as a service, Reasoner separate from Executive, observation
pipeline end-to-end, sandboxed simulation, event-bus spine. The charter's own rule —
*"Never redesign completed milestones without evidence"* — therefore governs: we
**preserve and extend additively**; we do not rewrite M1–M12.1.

---

## Charter reconciliation (status vs. existing code)

| # | Frozen decision | Status | Evidence / gap |
|---|---|---|---|
| 1 | World Model is center, not LLM | ✅ PRESENT | `core/world/world_model.py`; M12 IOS is a service, models get read-only context |
| 2 | Observation pipeline | ✅ PRESENT | `core/sensors`→`core/perception` (fusion→manager→world_feed)→`core/world` |
| 3 | Attention Manager | 🟠 PARTIAL | `core/attention` ranks; `PerceptionManager.significance` filters. No runtime queue/compute manager |
| 4 | Entity Resolver | 🔴 ABSENT | Name-based dedup only; no alias/variant resolution |
| 5 | Persistent Entity IDs | 🟠 PARTIAL | `entity_id = "{kind}:{name}"` — identity coupled to names (fragile) |
| 6 | World Model (beliefs, self, spatial/temporal) | 🟠 PARTIAL | entities+relationships+confidence+snapshots exist; no beliefs/self/spatial |
| 7 | Knowledge Graph over Entity IDs | 🟠 DIVERGENT | Two graphs: `world.db` entity rels vs M7 concept rels (`knowledge_links`) |
| 8 | Memory: Working/Episodic/Semantic/**Procedural** | 🟠 PARTIAL | Working/Episodic/Semantic/Archival exist; **no Procedural** |
| 9 | Self Model | 🟠 PARTIAL | `CognitiveState` tracks focus/goal/plan/task; no resources/sensors/agents/limits |
| 10 | Belief System {confidence, evidence, ts, source} | 🔴 ABSENT | confidence is scattered floats; no Belief primitive |
| 11 | Reasoning separate from Executive | ✅ PRESENT | `Reasoner` injectable; `ExecutiveBrain` delegates |
| 12 | Executive Intelligence (CEO) | ✅ PRESENT | `core/executive/executive.py` |
| 13 | Prediction Engine | 🔴 ABSENT | only sim-timeline extrapolation (M11) |
| 14 | Simulation (sandboxed, advisory) | ✅ PRESENT | `core/simulation/sandbox.py` isolation enforced |
| 15 | Learning Engine | ✅ PRESENT (fragmented) | M4 reflection, M7 learning, M9, M12 learning |
| 16 | Scientific Reasoning (Q→H→Sim→Evidence→Belief) | 🔴 ABSENT | strategies exist; no scientific-method pipeline |
| 17 | Architecture Optimizer | ✅ PRESENT | `core/intelligence/optimizer.py` + `core/review` |
| 18 | Autonomous Research Platform | 🔴 ABSENT | only `research_summarize` |
| 19 | General Cognitive Platform | — | final milestone |
| 20 | Own learned reasoning | — | directional |

**Load-bearing gaps cluster:** #4, #5, #10, #6, #9 are all the *entity/belief
substrate* that #13 (prediction), #16 (scientific reasoning), and #7 (entity graph)
depend on. Build this substrate first.

---

## Recommended next milestone — M13: Persistent Entity & Belief Foundation

> Additive, strangler-fig. No M1–M12.1 file modified except dependency-injection
> hooks. Must pass the M10 **Design Challenge Gate** before implementation.

### Design decisions (evidence-based recommendations; flagged for override)

1. **Entity identity = opaque stable ID + Entity Resolver** *(recommended over literal
   `PERSON_0001`)*. Each entity gets a name-independent stable id (`ENT_000123`); an
   **Entity Resolver** maps each observation to an existing id via an **alias table +
   fuzzy/normalization match**, or mints a new id. `kind:name` is kept only as a
   human-readable label. This satisfies decision #4's stated *intent* ("identity
   persists independently of names"), which typed counters do not (they still force a
   type guess at creation and don't solve duplication).
2. **Two complementary graphs, not a merge** *(recommended)*. Treat the existing
   `world.db` relationships as the charter's **entity graph** (extend it over the new
   stable ids); keep M7/M8's **concept graph** as the complementary semantic layer. No
   rewrite of completed M7/M8.
3. **Belief is a first-class primitive** layered over entities/world facts, not a
   replacement for existing `confidence` fields (those stay as fast-path scalars).

### Scope (modules — all additive)

- **Entity Resolver** — `resolve(...) -> stable_id`; alias table; normalization (reuse
  M6 fusion's app-name normalization); merge two ids; confidence-weighted matching.
- **Persistent Entity registry** — stable-id allocation + `label`/`kind` mapping;
  extends `core/world` entities **additively** (new `stable_id`, back-compat with
  `kind:name`) via a v2 migration through the M10 `MigrationRunner` (first real schema
  migration — proves that framework).
- **Belief System** — `Belief{subject(entity_id), predicate, value, confidence,
  evidence, source, timestamp}`; `BeliefStore` (SQLite, WAL, schema_version);
  `assert/revise/retract/query`; history kept; conflicts resolved by confidence+recency.
- **Self Model extension** — extend `CognitiveState` (via composition) to publish:
  active goals (M4), current tasks/plan (M5), compute/resources (M10 `ResourceMonitor`
  + M12 health), active sensors (M6 `SensorRegistry`), active agents (M11
  `AgentSociety`), confidence + workload + declared limitations.
- **Wiring (DI hooks only)** — `WorldFeed`/`PerceptionManager` route through the Entity
  Resolver before `WorldModel.observe`; promotions can emit beliefs. Pure injection;
  M6 files unchanged except an optional injected resolver.
- **Observability** — metrics (entities created/merged, duplicate-collision rate,
  beliefs asserted/revised), events on the M1 bus, health provider, Mission Control
  panel data, DecisionLog entries for merges.

### Critical files

- New: `core/cognition_core/{__init__,entity_resolver,entity_registry,belief,
  belief_store,self_model,service,events,dashboard}.py`.
- Reuse (read, do not modify): `core/world/world_model.py`, `core/world/entities.py`,
  `core/perception/world_feed.py`, `core/perception/manager.py`,
  `core/perception/fusion.py`, `core/executive/state.py`,
  `core/database/migrations/migration_runner.py`,
  `core/mission_control/resilience.py` (`safe_call`), `core/runtime/bus.py`.
- Data: `data/cognition.db` (or extend `world.db` via migration — decide in step 1).

### Tests (~6 files, broad coverage)

`test_entity_resolver` · `test_entity_registry` · `test_belief_system` ·
`test_self_model` · `test_world_migration` (v2 upgrade/validate/rollback) ·
`test_cognition_core_integration` (observation → resolver → stable entity → belief;
production isolation; dashboard payload).

### Benchmark

Resolver throughput + duplicate-collision rate on a synthetic observation stream
(charter #17 wants entity-resolution accuracy measured).

### Docs

`docs/M13_ENTITY_BELIEF.md` — architecture, the entity-identity decision + rationale,
belief model, self-model, migration, Mission Control integration, extension guide.

---

## Forward roadmap (sequenced — do NOT implement early)

M14 Prediction Engine (#13, needs entities+beliefs) → M15 Scientific Reasoning
(#16, Q→H→Sim→Evidence→Belief) → M16 Attention Manager formalization + Procedural
memory (#3, #8) → M17 Autonomous Research (#18) → … → final General Cognitive Platform
(#19). Each gated by the Design Challenge Gate; each additive.

---

## Verification (for M13 when built)

1. `python -m pytest -q` → 823 prior pass + new M13 tests (zero regressions).
2. Side-effect-free imports (no DB/model/process at import).
3. Migration: run the v2 `MigrationRunner` upgrade on a temp `world.db`, validate,
   confirm rollback restores v1.
4. End-to-end: feed a synthetic observation stream with name variants → one stable
   entity (no duplicates), a belief asserted with evidence, Self Model reflects live
   goals/resources/sensors.
5. Commit + tag `m13-complete`; update `FRIDAY_4.0_CHANGES.md`.

---

## Open decisions awaiting confirmation (defaults = recommendations above)

1. **M13 target** = Entity & Belief Foundation. (Alternatives — Prediction / Scientific
   Reasoning / Self+Attention — depend on this substrate.)
2. **Entity IDs** = opaque stable id + resolver (vs literal `PERSON_0001` vs
   `kind:name` + alias layer).
3. **Graphs** = entity graph + concept graph as two complementary layers (vs unify,
   which redesigns M7/M8).

Implementation will not begin until these are confirmed (charter: *"Wait for
verification before continuing"*).
