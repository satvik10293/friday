# M17 (revision) — Human Cognitive Architecture + M18 Foundation (FRIDAY V3)

> **Status:** complete (awaiting review). **Supersedes** the original M17 Perception Hub
> spec. FRIDAY is no longer independent modules; it is a **society of specialized
> Cognitive Brains**. Each brain owns local reasoning, state, and memory, and emits
> structured **Situation Reports**. The **Cognitive Coordinator** (the renamed/redesigned
> Perception Hub) merges them into **Unified Situations** and is the only gateway into the
> **Executive Brain** (the CEO, M18 foundation). A dedicated **Memory Brain** owns the
> tiered memory hierarchy + a semantic **Knowledge Graph**. Fully additive — M1–M17(hub)
> reused, nothing rewritten.

---

## 1. Migration report (what changed and why)

| Original M17 | Now | Reuse |
|---|---|---|
| Perception Hub fuses raw modality observations | **Cognitive Coordinator** fuses **Situation Reports** | Hub's `ConfidenceEngine` + `Timeline` reused directly |
| Sensors write memory/world separately | Each sensor is a **Cognitive Brain** with local memory; reports only | Vision/Audio/Spatial subsystems reused via services |
| Hub → World Model gateway | Coordinator → **Executive Brain** gateway; Memory Brain owns memory | M5 executive reused as optional planner; M2 memory as durable backend |
| (no tiered memory) | **Memory Brain**: Working→Core promotion + Knowledge Graph | M2 MemoryService wrapped for durability |

The M17 Perception Hub (`core/perception/hub/`) **remains intact and tested** (backward
compatible); the Coordinator reuses its engines rather than replacing them.

## 2. Architecture diagram

```
   ┌────────── Cognitive Brains (core/brains/*) — each: observe→analyze→update_local_memory ──────────┐
   │            →reason→generate_situation_report→publish→wait;  private local memory                  │
   │  Vision  Audio  Spatial  Learning  Emotion  Automation  Runtime         Memory Brain (tiers + KG) │
   └───────────────────────────────┬───────────────────────────────────────────────────────────────────┘
                                    │  Situation Reports (no raw data)
                                    ▼  Situation Report Bus
                          ┌───────────────────── Cognitive Coordinator ─────────────────────┐
                          │  merge · resolve conflicts · de-duplicate · maintain context ·   │
                          │  build Unified Situations                                        │
                          └───────────────────────────────┬──────────────────────────────────┘
                                                           │  Unified Situations (only)
                                                           ▼
                                   ┌──────── Executive Brain (CEO, M18) ────────┐
                                   │  decisions · planning · prioritization ·    │
                                   │  delegation · focus;  owns Working Memory   │
                                   └─────────────────────────────────────────────┘
   All arrows are service calls / bus messages. No brain imports another brain's internals.
```

## 3. Cognitive Brain mapping

| Brain | Wraps (via service) | Local memory | Reports |
|---|---|---|---|
| `vision_brain` | M14 vision | objects/faces/tracking/confidence | "I see N objects: …" |
| `audio_brain` | M15 audio | wake/speaker/noise/conversation | "I hear typing / **emergency**" |
| `spatial_brain` | M16 spatial | rooms/motion/object-locations | "user working in office; N tracked" |
| `memory_brain` | M2 memory (durable) | tiered hierarchy + Knowledge Graph | "Memory: X items; +K promoted" |
| `learning_brain` | LearningService | pattern candidates/reinforcement | candidate patterns (placeholder) |
| `emotion_brain` | EmotionService | mood/emotional/social | affective context (placeholder) |
| `automation_brain` | — (rules) | fired rules | trigger→action recommendations |
| `runtime_brain` | RuntimeService + container | event rate | "all systems nominal / degraded" |
| `executive_brain` | M5 executive (optional planner) | **Working Memory only** | (consumes situations; decides) |

Every brain implements the **standard lifecycle** and `tick()` runs it once, never-raises.

## 4. Cognitive Coordinator design

`CognitiveCoordinator` subscribes to the Situation Report Bus. Each cycle it groups
reports (emergencies stand alone; the rest fuse into one current picture), resolves
conflicts (mutually-exclusive user states → higher confidence wins, conflict recorded),
removes near-duplicate situations within a window, maintains active context (room /
activity / situation), builds a `UnifiedSituation`, and publishes it **only** to the
Executive Brain — plus threads it into the Memory Brain. Reuses the hub's
`ConfidenceEngine` (noisy-OR + agreement/conflict) and `Timeline`.

## 5. Memory Brain design

The single owner of memory (replaces direct memory access). `TieredMemory` promotes
items **Working → Short-Term → Episodic → Semantic → Long-Term → Core** by a score over
reinforcement, frequency, confidence, user confirmation, and importance; recall
reinforces (use-it-or-lose-it); stale low-tier memories are forgotten; episodic memories
**consolidate** into semantic summaries. High-tier memories persist to the M2 backend.

## 6. Local Memory

`LocalMemory` (base) gives every brain private named ring caches + a small key/value
store — never shared directly; peers see only Situation Reports.

## 7. Knowledge Graph

`KnowledgeGraph` (under the Memory Brain) is a live semantic entity-relationship graph
connecting people, objects, rooms, concepts, projects, habits, preferences, devices, and
relationships — with typed weighted edges, neighbors/`related`/shortest-`path` traversal,
and `connect()` convenience. The foundation for future reasoning.

## 8. Executive Brain foundation (M18)

`ExecutiveBrain` is the CEO. It receives **only** Unified Situation Reports (it **refuses**
any payload containing raw keys — frames, audio samples, detections, scene graphs,
queries), tracks **focus** by priority in **Working Memory** (its only memory), and
`decide()`s — delegating planning to the M5 executive when an objective + planner are
present, else acting on the current focus. All other memory goes through the Memory Brain
(`request_memory`).

## 9. Situation Report specification

`SituationReport`: `report_id`, `source_brain`, `timestamp`, `summary`, `confidence`,
`priority`, `category`, `evidence[]`, `local_memory_summary`, `recommended_action?`,
`data`. Published on the `SituationReportBus`. **No raw observations leave a brain.**

## 10. Service interface updates

`PerceptionServiceProtocol` (M17) plus the brain services: each brain exposes itself as
its one public service; `memory_brain` and `coordinator` and `executive_brain` register
into the M16 `ServiceContainer`. Communication is only via services + the Runtime/Report
buses.

## 11. Deployment improvements

Pure stdlib, no OS-specific logic, no hardcoded paths, plugin-extensible (automation
rules, knowledge-graph, reasoning), offline-capable, structured logging, configuration-
driven, graceful degradation (one brain failing never stops the society), multi-device
ready (services swappable/remote-able).

## 12. Test results

`tests/test_brains.py`, `test_memory_brain.py`, `test_coordinator.py`,
`test_executive_brain.py` cover the framework (reports/bus/local memory/lifecycle
never-raises), sensor brains, the Memory Brain (promotion/recall/forget/consolidate/
durable/graph threading), the Knowledge Graph (nodes/edges/path/find), the Coordinator
(merge/dedup/conflict/context/gateway/events/cycle/graceful degradation/no circular
imports), and the Executive Brain (receive/refuse-raw/focus/decide/working-memory-only).
All green; full suite (M1–M17rev) green.

## 13. Performance analysis

Bounded local memories (ring caches), bounded coordinator timeline, in-memory tiered
memory with capacity enforcement, never-raises everywhere. A full society `cycle()` is
microseconds of pure-Python work per brain.

## 14. Technical debt removed

Direct memory access is replaced by the Memory Brain gateway; raw cross-subsystem data
flow is replaced by Situation Reports; the Executive is decoupled from sensors entirely.
Removed dead imports; verified one-way dependencies (services/hub never import brains/
coordinator).

## 15. Remaining work before M19

- Wire the autonomous `cycle()` loop into the running spine (currently driven on demand).
- Migrate M16 spatial's direct World-Model writes through the Coordinator (additive
  deprecation) so the Hub→Coordinator is the sole world gateway.
- Flesh out Learning/Emotion/Automation brains beyond foundations.
- Persist the tiered memory + knowledge graph (currently in-memory + M2 durability for
  high tiers); add SQLite for the graph.
- Richer Executive planning/scheduling on top of the M5 planner.

See **architecture.json** (`core/coordinator/`) for the machine-readable manifest.
