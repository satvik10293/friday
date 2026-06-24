# M6 — Perception & Awareness Layer

> Strangler-fig, **completely additive**. No M1–M5 file was modified. Two new
> packages: `core/perception/`, `core/sensors/` (+ `core/sensors/builtin/`).
> **Test status: 269 passed** (M1 20 · M2 27 · M3 44 · M4 33 · M5 74 · **M6 71**).
> 100% local — no cloud, no external AI model.

M6 turns FRIDAY from a goal-driven *thinking* system into a **perception-driven**
thinking system. She can now sense system state, track changes, fuse corroborating
observations, promote important facts into her world model, focus attention on
what changed, and **reason about current reality** — all locally.

---

## Pipeline

```
   M1        M6                       M5             M5         M5/M6 brain    M4       M3        M3       M1/M3
┌────────┐ ┌────────────┐ ┌──────────┐ ┌───────────┐ ┌───────────────────┐ ┌──────┐ ┌────────┐ ┌────────┐ ┌──────┐
│Runtime │→│ Perception │→│ World     │→│ Attention │→│ Executive Brain   │→│Goals │→│ Skills │→│Security│→│Audit │
└────────┘ └────────────┘ │ Model(M5) │ └───────────┘ │ (PerceptiveBrain) │ └──────┘ └────────┘ └────────┘ └──────┘
   ▲          ▲    ▲       └──────────┘                └───────────────────┘
   │          │    │
 Sensors ─────┘    └── promotion: high confidence · high significance · repeated · goal-relevant

 Expanded cognitive loop (PerceptiveCognitiveLoop):
 Observe → Fuse → Context → World → Attention → Reason → Plan → Select → Execute → Reflect → Learn
```

Perception is **inserted at the front** of the pipeline. Sensors feed it, it feeds
the M5 World Model; attention and the Executive Brain consume the result. Execution
still flows through the M3 `SkillExecutor`; nothing bypasses existing layers.

---

## Packages & modules

### `core/perception/` — perception layer
| Module | Role |
|---|---|
| `models.py` | `Observation` (id, timestamp, source, type, confidence, payload, metadata) + `ObservationType` (system/screen/vision/audio/user_activity/filesystem/network/application/time/custom), `ObservationConfidence` (bands + `level`), `ObservationSource`, `ObservationBatch`, `new_observation`. Pure data; `subject()`/`value_signature()` drive dedup. |
| `events.py` | `PerceptionEvent` str-enum: `observation.received/changed/ignored/promoted/archived` — bus keys without touching `Signal`. |
| `store.py` | `PerceptionStore` — SQLite (`data/perception.db`): `observations`, `observation_history`, `sensor_health`, `sensor_metrics`, `schema_version`. Per-thread conns + WAL. Survives restart. |
| `fusion.py` | `SensorFusion` + `FusionRule` + `noisy_or`. Combines corroborating observations (screen "Chrome" + process "chrome.exe" → one APPLICATION "Chrome" with boosted confidence). Rules pluggable. |
| `manager.py` | `PerceptionManager` — **dedupe, merge repeats, track history, compute significance, promote to world model, archive low-value**. Bridges to M5 Attention via `focus()`. |
| `health.py` | `PerceptionHealth` + `HealthStatus` + `aggregate()` / `derive_status()`. |
| `world_feed.py` | `WorldFeed` — adapter letting the M5 WorldModel "observe Observation objects" via its **existing** `observe()` API (no world_model.py edit). |
| `brain.py` | `PerceptiveBrain(ExecutiveBrain)` — adds `observe`/`analyze_environment`/`current_environment`/`important_changes` (PACKAGE 8) via subclass. |
| `cognition.py` | `PerceptiveCognitiveLoop(CognitiveLoop)` — adds **Observe + Fuse** as first-class phases (PACKAGE 9) via subclass. |

### `core/sensors/` — sensor framework
| Module | Role |
|---|---|
| `base.py` | Abstract `Sensor` (name/version/type/interval, `capabilities`/`health`/`start`/`stop`/`observe`). `poll()` wraps `observe()` with error isolation + metrics. Local-only by contract. |
| `registry.py` | Thread-safe `SensorRegistry` (register/unregister/get/list/health, duplicate-guarded). |
| `manager.py` | `SensorManager` — polls sensors, collects observations, optionally fuses, feeds the Perception Manager, records sensor health/metrics, `attach(runtime)` for periodic polling. |
| `heartbeat.py` | `Heartbeat` + `HeartbeatMonitor` — liveness tracking (`beat`, `is_stale`, `stale`). |
| `builtin/system_sensor.py` | cpu/ram/disk/battery/uptime (psutil optional, degrades). |
| `builtin/time_sensor.py` | hour/day/week/month/timezone/part-of-day (stdlib, deterministic). |
| `builtin/process_sensor.py` | running processes, active process, started/ended changes (psutil optional). |
| `builtin/filesystem_sensor.py` | watched dirs: new/modified/deleted files (stdlib, diffs across polls). |

---

## The perception decision flow (PerceptionManager.ingest)

```
observation → subject + value-signature
  ├─ unseen subject ......................... status = received
  ├─ seen, same values ...................... status = ignored  (merge: count++)
  └─ seen, different values ................. status = changed
significance = 0.30·novelty + 0.30·confidence + 0.20·impact + 0.20·goal_relevance
  ├─ promote?  high confidence AND (high significance OR repeated≥3 OR goal-relevant)
  │      → WorldFeed.observe() → world entity ; event observation.promoted
  └─ archive?  duplicate AND significance ≤ 0.15  → event observation.archived
every step: persisted to data/perception.db + appended to observation_history + event on the bus
```

**Promotion rules (PACKAGE 6):** high confidence, high significance, repeated
occurrence, or goal relevance — exactly as specified.

**Attention integration (PACKAGE 7):** `focus()` projects recent observations into
the shape M5 `AttentionSystem.rank_observations` consumes (importance from
confidence·novelty, urgency from impact, priority from goal-relevance), so
attention can now rank observations alongside goals and memories.

---

## Integration strategy (additive; no M1–M5 edits)

The spec's PACKAGE 8/9 ("ExecutiveBrain gains…", "Expand M5 loop") conflict with
the hard rule "No M1–M5 files may be modified." **The stricter rule wins:**
integration is delivered by **subclasses + an adapter**, so M1–M5 stay pristine and
all 198 prior tests keep passing unchanged.

| Requirement | Delivered as (additive) |
|---|---|
| `world.observe()` accepts Observation | `WorldFeed.observe(obs)` adapter → existing `WorldModel.observe(kind,name,state,…)` |
| ExecutiveBrain gains `observe`/`analyze_environment`/… | `PerceptiveBrain(ExecutiveBrain)` subclass — a drop-in superset |
| Expand the cognitive loop with Observe+Fuse | `PerceptiveCognitiveLoop(CognitiveLoop)` subclass |
| Attention focuses on observations | `PerceptionManager.focus()` → `AttentionSystem.rank_observations` (M5 used unchanged) |
| events / scheduling / health | M1 `Runtime` (`emit`, `schedule`, `register_health`) — `PerceptionEvent` is a `str`-enum bus key |

No cloud dependency anywhere; psutil is the only optional binding and it degrades to
a low-confidence "unavailable" observation when missing.

---

## Persistence (PACKAGE 10)

`data/perception.db` — per-thread connections + WAL + `schema_version`. Tables:
`observations`, `observation_history`, `sensor_health`, `sensor_metrics`,
`schema_version`. Observations and their history survive restart
(`test_observations_survive_restart`).

---

## Tests — 71 new (269 total, no M1–M5 regressions)

| File | Count | Covers |
|---|---|---|
| `tests/test_sensors.py` | 17 | base poll + **error isolation**, capabilities/lifecycle, registry CRUD+duplicate+health, heartbeats + staleness, manager register/collect/**poll_once feeds perception**/failing-sensor isolation, all four built-ins. |
| `tests/test_perception.py` | 16 | observation model/roundtrip/signature, confidence levels, batch, **dedupe (received/ignored/changed)**, significance, **archival**, history, **promotion to world**, stats, **restart recovery**, store counts/by-type. |
| `tests/test_fusion.py` | 10 | noisy-or math, **screen+process → Chrome**, single-source no-fusion, entity metadata, fuse_and_merge, distinct-app separation, custom rule, name normalization, metrics. |
| `tests/test_observation_world.py` | 9 | WorldFeed entity creation/metadata/state-merge, **promotion by confidence**, **by repetition**, low-confidence never promotes, **by goal relevance**, promoted query, batch feed. |
| `tests/test_environment_reasoning.py` | 10 | `observe` polls+ingests+promotes, `current_environment`, `important_changes` ranked, **`analyze_environment` reasons about reality**, reasoning metric, **ExecutiveBrain backward-compat**, health includes perception+sensors. |
| `tests/test_cognition_perception.py` | 9 | **all 11 phases (observe+fuse first)**, sensors feed world inside the cycle, planning/acting on goals, auto_execute off, metrics, idempotent start/stop, learning stored, status, **cycle event**. |

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
# expected: 269 passed
```

---

## Success criteria — met

| FRIDAY can… | Where |
|---|---|
| Observe system state | built-in sensors + `SensorManager` |
| Track changes | `PerceptionManager` dedup/changed status + `observation_history` |
| Fuse multiple observations | `SensorFusion` (noisy-or, application detection) |
| Promote important facts | `PerceptionManager.promote` → `WorldFeed` |
| Update the world model | M5 `WorldModel` via `WorldFeed` |
| Focus attention on important events | `PerceptionManager.focus` → M5 `AttentionSystem` |
| Reason about current conditions | `PerceptiveBrain.analyze_environment` |
| Use real-world observations in planning | `PerceptiveCognitiveLoop` (Observe→Fuse→…→Plan) |
| …without external AI models, locally | psutil-optional sensors; zero cloud calls |

---

## Design decisions

- **Additive via subclass/adapter, not edits.** The hard "no M1–M5 modification"
  rule is honored exactly. `PerceptiveBrain`/`PerceptiveCognitiveLoop` are supersets;
  `WorldFeed` adapts to the existing world API. Zero risk to prior tests.
- **Dedup by subject + value-signature.** An observation's *subject* identifies the
  thing; its *value-signature* identifies the reading. Same subject + same values =
  a merge (count++), not a new fact — keeping the store and world model from bloating.
- **Corroboration only increases certainty.** Fusion combines confidence with a
  noisy-or, so two weak sensors agreeing produce a stronger fact than either alone.
- **Significance is explainable.** Every promotion/archival decision is a weighted,
  inspectable function of novelty, confidence, impact, and goal-relevance.
- **Local-only, degrade-don't-fail.** psutil is optional; a missing sensor or a bad
  poll yields a contained low-confidence/empty result, never an exception that breaks
  the manager.

---

## Not yet done (next)

- **Real screen / vision / audio sensors** feeding `ObservationType.SCREEN/VISION/AUDIO`
  (the fusion rules already anticipate screen↔process corroboration).
- **LLM-backed environment reasoning** behind `analyze_environment` (the
  ContextPackage it builds is LLM-ready).
- **Wire perception into the spine** (`friday_spine`/`friday_proactive`) so the live
  app senses continuously — needs Git (edits live 3.0 code).
- **Mission Control:** surface the observation stream, promotions, and sensor health.
