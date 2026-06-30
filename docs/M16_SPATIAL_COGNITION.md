# M16 — Spatial Cognition + Service Layer (FRIDAY V3)

> **Status:** complete (awaiting review). **Goal:** turn "I see objects" into "I
> understand the environment" — object permanence, location, relationships, movement,
> room structure, user position, change. M16 also introduces the **service layer**: from
> here on, subsystems communicate ONLY through dependency-injected services, never by
> importing another subsystem's internals. Fully additive; M1–M15 unchanged.

---

## 1. Design philosophy

Humans remember *relationships*, not pixels. So FRIDAY stores

```
Phone → on Desk, beside Keyboard, inside Office, last seen 09:34, confidence 96%
```

not `Phone (x=410, y=280)`. The Scene Graph is that relational memory.

---

## 2. Architecture

```
                         ┌──────────────── Service Layer (core/services) ───────────────┐
   VisionService ─┐      │ RuntimeService  WorldModelService  MemoryService              │
   AudioService ──┼─────►│ AttentionService  ExecutiveService  ConfigurationService      │
                  │      │ PluginService  LearningService*  EmotionService*  Vision/Audio │
                  │      └───────────────────────── ServiceContainer (DI) ───────────────┘
                  │                                   ▲          │
            SpatialObservation                        │          ▼  (events on Runtime bus)
                  │                          ┌─────────┴──────────────────────────────┐
                  └─────────────────────────►│            SpatialEngine                │
                                             │  rooms → tracker → scene graph →        │
                                             │  relationships → localization →         │
                                             │  world model → spatial memory → events  │
                                             └───────────────┬─────────────────────────┘
                                                             ▼
                                        SpatialService.query()  ·  SceneGraph (persistent)
```

`*` = placeholder service (stable API now, implementation in M17+).

Every arrow is a **service call**. The spatial engine imports no other subsystem's
internals; it consumes source-agnostic `SpatialObservation`s and talks to the world only
through services obtained from the `ServiceContainer`.

---

## 3. Files created

**Service layer (`core/services/`)** — `interfaces.py` (12 Protocols + `ServiceName`),
`container.py` (`ServiceContainer` DI + `build_default_container`), and the wrappers:
`runtime_service`, `world_model_service`, `memory_service`, `attention_service`,
`vision_service`, `audio_service`, `executive_service`, `configuration_service`,
`plugin_service`, `learning_service` (placeholder), `emotion_service` (placeholder),
`__init__.py`.

**Spatial subsystem (`core/spatial/`)** — `config.py`, `events.py`, `interfaces.py`
(`SpatialObservation` + strategy Protocols), `scene_graph.py`, `tracker.py`,
`relationships.py`, `rooms.py`, `localization.py`, `memory.py`, `queries.py`, `engine.py`,
`service.py`, `benchmark.py`, `architecture.json`, `__init__.py`.

**Tests** — `tests/test_services.py`, `test_spatial_scene_graph.py`,
`test_spatial_tracker.py`, `test_spatial_relationships.py`, `test_spatial_cognition.py`,
`test_spatial_engine.py`. **Docs** — this file.

## 4. Files modified
None (M16 is purely additive — no existing milestone file was changed).

---

## 5. Service interfaces added

`ServiceProtocol` (base: `name` + `health()`), `RuntimeServiceProtocol`,
`WorldModelServiceProtocol`, `MemoryServiceProtocol`, `AttentionServiceProtocol`,
`VisionServiceProtocol`, `AudioServiceProtocol`, `SpatialServiceProtocol`,
`ExecutiveServiceProtocol`, `ConfigurationServiceProtocol`, `PluginServiceProtocol`,
`LearningServiceProtocol`, `EmotionServiceProtocol`. Any object structurally satisfying a
protocol (real wrapper, mock, or future remote proxy) can be injected.

## 6. Event Bus events added

`spatial.object.detected · tracked · moved · lost · returned · removed`,
`spatial.scene.updated`, `spatial.relationship.changed`, `spatial.room.changed`,
`spatial.user.moved`, `spatial.user.located`, `spatial.scene.loaded`, `spatial.scene.saved`.

---

## 7. Scene Graph

A persistent tree where everything — rooms, furniture, objects — is a `SceneNode`
(UUID `node_id`, `persistent_id`, `object_class`, `label`, `parent`, `children`,
`position`, `relationships`, `confidence`, `created/updated/last_seen`, `room`, `session`,
`status`). Objects parent to their room; relationships (on/beside/near/…) capture finer
structure. In-memory authoritative for speed, with SQLite write-through (per-thread WAL)
so it survives restarts (`save()`/`load()` recover the full graph + child links).

**Object tracking** gives nodes persistent identity across frames and short
disappearances — `NEW · TRACKED · MOVED · LOST · RETURNED · REMOVED` — via greedy
one-to-one matching on class + normalized-centre distance (plus a `stable_id` fast path),
preventing duplicate identities.

**Relationships** (`relationships.py`) infer the full M16 vocabulary
(on/under/inside/near/beside/left_of/right_of/behind/in_front_of/touching/attached_to/
contained_by) from normalized geometry, are recomputed each update, and only *changes*
are published/persisted.

---

## 8. Runtime integration

The engine talks to the runtime only through `RuntimeService`: it publishes the spatial
events above (delivered to local subscribers synchronously and forwarded to the async M1
bus for Mission Control). Health registers via `attach(runtime)`. With no runtime wired,
the RuntimeService runs a self-contained in-process bus, so spatial cognition (and tests)
work standalone.

## 9. Memory integration

`SpatialMemory` (SQLite) stores meaningful events (object, room, relationships, timestamp,
confidence, session) and per-object movement history, suppressing redundant repeats.
Significant events are forwarded to long-term memory / Chronicle through `MemoryService`
(duck-typed; never importing memory internals). The query engine answers *where is my
phone / where did I last leave my wallet / what changed today / which room contains my
laptop / what moved while I was gone* over the graph + memory (backend only, no GUI).

---

## 10. Deployment improvements

- **Cross-platform:** pathlib + portable SQLite (shared-cache URI for in-memory); no
  OS-specific calls; **no hardcoded paths** (the DB resolves to the project root unless
  `memory.db_path` is set).
- **Camera abstraction:** spatial consumes observations via `VisionService` — USB,
  built-in, IP, or future mobile/multi-camera all arrive as `SpatialObservation`s; the
  source is swappable without touching spatial.
- **Configuration-driven:** every tunable in `SpatialConfig`; the `audio:`-style flat
  block or nested sections both parse.
- **Plugin support:** `PluginService` registers camera adapters, room classifiers, and
  relationship rules by name — extend without modifying core logic.
- **Graceful recovery:** the engine never raises; `save()`/`load()` restore the scene
  after restart; missing services degrade to safe fallbacks.

## 11. Performance analysis

Incremental per-update work, periodic pruning (`object_timeout`), bounded movement
history, in-memory authoritative graph with SQLite write-through. Benchmark
(`python -m core.spatial.benchmark`, CPU): hundreds of multi-object updates/second; the
graph stays bounded by persistent identity + pruning over a long session.

## 12. Test results

Six test files cover the service layer (DI, decoupling, mockability, fallbacks), scene
graph (CRUD, reparent, lifecycle, pruning, persistence recovery), tracking (all six
states, no duplicate ids, stable-id path), relationships (every relation incl. correct
left/right and z-gated depth), rooms/localization/memory/queries, and the engine/service
integration (events, World-Model writes, recovery, vision poll, never-raises, long-session
performance, benchmark, no circular imports). All green (see audit run).

## 13. Known limitations

- **2D relationship inference:** without depth, a small object whose bbox sits inside a
  larger one reads as `inside`/`contained_by` rather than `on`; `behind`/`in_front_of`
  are only emitted when explicit `z` is present. A depth camera or a learned inferencer
  (injectable via `PluginService`) resolves this.
- **Re-identification across large jumps:** an object that moves farther than
  `tracker.match_distance` in one frame (without a `stable_id`) is treated as a new
  identity until the old one ages out. Incremental motion tracks correctly; vision-supplied
  `stable_id`s bridge any gap.
- **User pose** (sitting vs standing) is heuristic without a pose signal; M15 pose output
  can feed it later.
- **Single-room geometry:** rooms are symbolic (membership), not metric floor-plans yet.

## 14. Recommendations for M17

- **Spatial reasoning / prediction:** "the user usually leaves the phone on the desk" —
  feed movement history + the World Model into prediction/simulation.
- **Multimodal fusion:** correlate `spatial.user.located` with M15 audio presence and M14
  vision for higher-confidence localization (a natural sensor-fusion milestone).
- **Metric mapping:** per-camera calibration → world coordinates + a real floor-plan,
  populating `position.z` so depth relationships become reliable.
- **Learned strategies:** replace the heuristic relationship/room/user estimators via the
  `PluginService` + the `LearningService` buffer already collecting samples.

See **architecture.json** for the machine-readable manifest.
