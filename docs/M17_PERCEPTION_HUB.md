# M17 — Multimodal Intelligence & Perception Hub (FRIDAY V3)

> **Status:** complete (awaiting review). **Goal:** stop FRIDAY thinking in separate
> modules. Vision, audio, and spatial no longer each write memory; every sensor publishes
> observations and a central **Perception Hub** fuses them into ONE unified cognitive
> event, reasons about it, maintains context + timeline, forwards understanding to the
> World Model, and remembers only meaningful, non-duplicate events. Additive; M1–M16
> unchanged. Lives under `core/perception/hub/` so the M6 perception package
> (`core/perception/*.py`) is untouched.

---

## 1. From modules to unified cognition

```
Before:   Vision → Memory      After:   Vision ┐
          Audio  → Memory               Audio  ┼─► Perception Hub ─► Unified Observation
          Spatial→ Memory               Spatial┘        │
                                                         ▼
                                   World Model ◄─ (gateway) ─► Executive ─► Memory ─► Learning
```

Every observation becomes one unified cognitive event.

---

## 2. Architecture & Perception-Hub diagram

```
 VisionService ─┐
 AudioService ──┼─ ModalityObservation ─►┌─────────────── PerceptionHub ──────────────┐
 SpatialService ┘                        │  FUSE → CONFIDENCE gate (+enrich) → REASON  │
        (all via core/services DI)       │   → CONTEXT update → TIMELINE → World Model │
                                         │   (gateway) → Memory (dedup/compress)        │
                                         └───────────────┬──────────────────────────────┘
                                                         ▼  events on the Runtime bus
                            ObservationCreated/Merged/Rejected · ReasoningCompleted
                            ContextChanged · SituationChanged · TimelineUpdated · PerceptionReady
```

Every arrow is a **service call**; the Hub imports no subsystem's internals.

---

## 3. Files created
**`core/perception/hub/`:** `config.py`, `observations.py`, `events.py`, `interfaces.py`,
`confidence.py`, `fusion.py`, `context.py`, `timeline.py`, `reasoning.py`, `hub.py`,
`service.py`, `benchmark.py`, `architecture.json`, `__init__.py`.
**Tests:** `tests/test_perception_hub_units.py`, `tests/test_perception_hub.py`.
**Docs:** this file.

## 4. Files modified
- `core/services/interfaces.py` — **additive**: added `PerceptionServiceProtocol` +
  `ServiceName.PERCEPTION` (and to `ServiceName.ALL`).
- `tests/test_services.py` — updated the "wires all services" test to skip the two
  self-registering services (`spatial`, `perception`).

No M1–M16 behavior changed.

## 5. New services
`PerceptionService` (satisfies `PerceptionServiceProtocol`): `ingest` / `perceive` /
`situation` / `context` / `timeline`, registered into the container as `perception`.

## 6. Event Bus additions (documented in `events.py`)
`perception.observation.{created,updated,merged,rejected}`, `perception.context.changed`,
`perception.timeline.updated`, `perception.ready`, `perception.reasoning.completed`,
`perception.situation.changed`.

---

## 7. Observation model

`ModalityObservation` (per-sensor input: source, category, label, confidence, location,
objects, people, timestamp, data). `UnifiedObservation` (the fused event) carries every
mandated field: id, timestamp, session_id, source_modules, confidence, location,
related_objects, related_people, audio_context, spatial_context, previous_context,
importance, event_category, conclusions, sources.

## 8. Fusion pipeline

`MultimodalFusion` groups a cycle's modality observations by location and merges each
group into one `UnifiedObservation` — vision contributes objects/people, audio the sound
context, spatial the room + user state. The `ConfidenceEngine` fuses certainties via
**noisy-OR** (independent corroboration raises certainty) with an **agreement boost** and
a **conflict penalty**; conflicts (e.g. one sensor says present, another unavailable) are
detected and handled gracefully. Borderline observations are **enriched** from context
(same room + overlapping objects) before being rejected.

## 9. Timeline architecture

`Timeline` is a bounded, thread-safe chronological ring of unified observations with
temporal operators **before / after / during / recently / current / historical** (+
`by_category`). Capacity-bounded for long sessions; future milestones (prediction,
planning, episodic memory) query it.

## 10. Reasoning

`CognitiveReasoner` runs modular `(unified, context) → conclusion?` rules and returns
what fired. Built-ins cover the spec examples — doorbell @ front door → *someone arrived*;
laptop + keyboard + typing → *user is working*; phone + room + no user → *phone left
behind*; bottle + running water + kitchen + morning → *preparing breakfast*. New rules
register without touching the engine (or inject a learned/LLM reasoner via `PluginService`).
This is understanding, not planning.

## 11. Runtime / Memory / Executive integration

- **Runtime:** events flow through `RuntimeService` (local delivery + forward to the M1
  async bus). Health via `attach(runtime)`.
- **World Model:** the Hub is the unified gateway — it writes the fused `situation`
  entity via `WorldModelService` (the sanctioned path going forward; M16's lower-level
  writes remain untouched per the no-rewrite rule).
- **Memory:** only meaningful unified observations are stored; identical situations within
  a window are **compressed** to one memory (semantic consistency, no duplicates).
- **Executive:** on a situation change the Hub provides understanding (`situation()` —
  current situation, room, activity, objects, important changes); it never plans.

## 12. Deployment improvements

Pure stdlib (no new dependencies, no numpy), no OS-specific logic, no hardcoded paths,
plugin-extensible (fusion/reasoning strategies), offline-capable, graceful degradation
when services are absent, structured `[Perception]` logging, configuration-driven, and
multi-device-ready (services are swappable/remote-able).

## 13. Test results

Two test files (units + integration) cover the observation model, confidence (noisy-OR,
agreement/conflict), fusion (modality merge, combined confidence), context (change +
situation), timeline (all temporal queries + bounded capacity), reasoning (every rule +
extensibility + isolation), and the hub/service (fusion→unified→reasoning, World-Model
gateway, memory compression, rejection + enrichment, perceive-from-services, executive
understanding, never-raises, long-session performance, benchmark, no circular imports,
side-effect-free). All green (see audit run). Benchmark: hundreds of cycles/second,
bounded timeline.

## 14. Known limitations

- **Heuristic reasoning:** rules are deterministic templates; richer/learned reasoning is
  the upgrade path (LLM/learned reasoner via `PluginService`).
- **Dual World-Model writers:** the Hub is the unified gateway, but M16 spatial still
  writes lower-level entities directly (removing that would rewrite M16). A future
  milestone can route spatial writes through the Hub.
- **Fusion grouping is by location + time window**, not yet by tracked-object identity
  across modalities (cross-modal re-ID is future).
- **Conflict handling is coarse** (one exclusive-state rule); a fuller belief-revision
  model belongs with the M13 belief system.

## 15. Recommendations for M18

- **Prediction & anticipation** over the timeline (the user usually makes breakfast at
  08:00 → pre-empt) feeding the planner/simulation.
- **Cross-modal entity fusion:** unify vision + spatial + audio onto the M13 persistent
  entity ids so "the phone" is one thing across senses.
- **Belief integration:** route unified observations through the M13 belief system for
  confidence revision + contradiction handling.
- **Hub as sole World-Model gateway:** migrate M16 spatial writes through the Hub (additive
  deprecation) to fully realize "only the Hub updates the World Model".

See **architecture.json** for the machine-readable manifest.
