# M11 — Interactive Cognitive Space

> Strangler-fig, **completely additive**. New package `core/cognitive_space/`.
> **Tests: `test_cognitive_space.py` (9) · `test_zoom_levels.py` (9).** Reuses the
> M10 auth + security headers + resilience and the vendored Three.js.

The navigable 3D universe of FRIDAY's mind — the visible face of the agent society
and the simulation engine, integrated with Mission Control.

---

## Six zoom levels (Part 5)

| Level | Name | Shows |
|---|---|---|
| 1 | **Universe** | entire FRIDAY — goals, knowledge, projects, agents, models, simulations |
| 2 | **Domain** | knowledge domains · agent teams · goal clusters |
| 3 | **Team** | leaders + their worker templates |
| 4 | **Agent** | individual leaders + reputation-rated workers |
| 5 | **Task** | assignments, communication, outputs (lifecycle) |
| 6 | **Thought Chain** | reasoning steps (e.g. a simulation's steps) — knowledge retrieval, decision formation |

`CognitiveSpace.build(level, focus)` returns nodes + edges + spatial partition for a
level. Every builder is **resilient** (`safe_call`) — a missing/failing subsystem
yields fewer nodes, never a crash (`CognitiveSpace()` with *no* services still
renders the FRIDAY core).

---

## Visual language (Part 10)

| Entity | Visual | |
|---|---|---|
| Knowledge | **Stars** | `#4da3ff` |
| Goals | **Attractors** | `#ffcc55` |
| Agents | **Living entities** | `#b48cff` |
| Tasks | **Energy streams** | `#ff8a5c` |
| Decisions | **Convergence events** | `#ff5d6c` |
| Simulations | **Separate universes** | `#5cf2e0` |

---

## Scalability by design (Parts 10 & 12)

- **LOD budgets** (`zoom.py`) — each level caps nodes (Universe 64 … Task 2048) so a
  frame never ships more than it can render at 60 FPS; deeper zoom shows *more of
  less*.
- **Deterministic layout** — `place()` on a Fibonacci sphere (stable positions for
  camera-focus and culling).
- **Spatial partitioning** — `partition()` buckets nodes into a cells³ grid for
  frustum culling / streaming. Verified to bucket **100,000 nodes** without
  redesign (the data layer targets 100k nodes / 1M relationships / 10k agents / 100
  simulations).
- Client uses **instanced** point/sphere rendering + the same budgets.

---

## Global search (Part 11)

`GlobalSearch.search(query)` searches **knowledge, goals, projects, agents, tasks,
models, simulations, events** at once; every hit carries a **camera-focus target**
(`{level, node_id}`) so the UI flies straight to it. Resilient per source.

---

## The UI (`ui.py` + `server.py`)

A single-screen Three.js universe: zoom-level navigator (not tabs — the same
universe at different detail), global search with camera focus, node inspection,
timeline scrubber, and simulation playback controls. Offline: Three.js is served
same-origin from the vendored `/static/three.module.js`; absent it, a 2D-canvas
fallback still renders the universe.

The server (`CognitiveSpaceServer`, localhost, port 5060) reuses the **M10 auth
layer** — read APIs open, **simulation control writes require authentication** —
and applies the M10 security headers to every response. Flask is imported lazily;
the module is side-effect-free.

### Mission Control integration
The cognitive space composes the same injected subsystems Mission Control uses and
exposes `build()/search()/zoom_levels()/visual_language()` — ready to mount as a
Mission Control view or run standalone at `:5060`.

---

## Vendoring Three.js (offline 3D)

```powershell
Invoke-WebRequest https://unpkg.com/three@0.160.0/build/three.module.js `
  -OutFile core/mission_control/static/three.module.js
```

It's a regenerable dependency (gitignored), shared by Mission Control and the
cognitive universe. Without it, both HUDs use their 2D fallback.
