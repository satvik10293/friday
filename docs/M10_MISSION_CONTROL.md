# M10 — Mission Control & Architecture Hardening

> Strangler-fig, **completely additive**. No M1–M9 file was modified. Seven new
> packages: `core/mission_control/`, `core/security/auth/`, `core/database/`,
> `core/agent_runtime/`, `core/embeddings/`, `core/retrieval/`, `core/review/`.
> **Test status: 586 passed** (M1–M9 500 · **M10 86**). 100% local, privacy-first,
> no cloud dependency.

M10 is two milestones at once: it builds **Mission Control** — FRIDAY's operational
cockpit — *and* resolves the highest-priority risks from `docs/ARCHITECTURE_REVIEW.md`
(unauthenticated writes, no migration runner, GIL-bound agents, keyword-only
retrieval) so no future milestone has to stop for security, migration, or
observability repairs.

This doc covers Mission Control + resilience; see the companion docs for security,
migrations, agent prep, and the review system.

---

## What Mission Control is

A single-screen **hybrid HUD** — not a dashboard, website, or chat. 3D (Three.js /
WebGL) for cognitive *structures*, 2D overlays for operational *state*. No tabs, no
hidden menus, no page switching: everything visible at once.

```
                         ┌───────────────── 3D scene (WebGL) ─────────────────┐
  [2D] Cognitive State   │  Knowledge galaxy (blue)  +  Goal network (amber)  │  [2D] Resources
                         │     orbit · zoom · live node clouds                │
  [2D] Security Center   └────────────────────────────────────────────────────┘  [2D] Event Stream
                                   [2D] ⚠ Critical alerts (center, on demand)
```

| Visualization | Rendered as |
|---|---|
| Knowledge Graph, Goal Network, Agent Teams, Cognitive State, World Model | **3D** (Three.js/WebGL/GPU) |
| Alerts, Resources, Security, Approvals, Critical failures | **2D overlays** |

Pure 3D is forbidden; the architecture is hybrid HUD + 3D by design.

---

## Packages

### `core/mission_control/`
| Module | Role |
|---|---|
| `service.py` | `MissionControl` facade — composes everything; `state()`/`panel()`/`health()`/`attach()`; `get_mission_control()` singleton. |
| `aggregator.py` | `MissionControlAggregator` — builds the 7 panels from injected subsystems, each through `safe_call`. |
| `resources.py` | `ResourceMonitor` — CPU/RAM/GPU/disk (psutil, optional) + database health + model health (M10 model registry). |
| `events.py` | `EventStream` — bounded ring buffer; the live timeline; `attach_runtime()` to capture bus events. |
| `resilience.py` | `safe_call` / `Degraded` — graceful degradation primitives (Part 7). |
| `ui.py` | `render_hud()` — the single self-contained HUD page (Three.js 3D + 2D overlays; offline; 2D-canvas fallback). |
| `server.py` | `MissionControlServer` — authenticated Flask server (lazy import); security headers on every response; **no write without auth**. |

### Core panels
1. **Cognitive State** — focus · active plan · current goal · confidence · context · brain status (from M5 Executive Brain).
2. **Goal Network** *(3D)* — active/blocked goals, dependencies, progress, priority (from M4) as nodes+edges.
3. **Knowledge Space** *(3D galaxy)* — concepts, relationships, growth, confidence, clusters (from M7/M8 via `portal_graph`).
4. **Agent Team Space** *(3D, M11-ready)* — team leaders, sub-agents, create/destroy events, communication; today reports the process-runtime metrics.
5. **Resource Monitor** — CPU/RAM/GPU/disk/database/model health.
6. **Security Center** — auth events, failed access attempts, tokens (from the M10 auth audit).
7. **Event Stream** — real-time timeline of everything happening in FRIDAY.

---

## Part 7 — Resilience (graceful degradation)

Every subsystem read goes through `safe_call(system, fn)`: on any exception it
returns a `Degraded` marker instead of propagating. The cockpit therefore keeps
operating when **memory, knowledge, portal, agent runtime, executive brain, or the
embedding service** fails — individual panels degrade; the whole never collapses.
Tested directly: an `Exploding` subsystem injected for every provider still yields
`operational: True` with the failures listed in `degraded`.

---

## Offline 3D

Three.js is loaded from a **same-origin** `/static/three.module.js` (vendored, no
CDN — honoring no-cloud). If it isn't vendored, the HUD detects the failed import
and falls back to a 2D canvas renderer, so the cockpit works either way. To enable
3D, drop `three.module.js` into `core/mission_control/static/`.

---

## Running

```python
from core.mission_control import get_mission_control
mc = get_mission_control(goal_service=..., knowledge_service=..., executive=...,
                         agent_runtime=..., authenticator=...)
mc.server(port=5050).run()      # http://127.0.0.1:5050  (authenticated, localhost-only)
```

Reads (`GET /`, `/api/state`, `/api/events`, `/api/health`) are open by default
(flip the authenticator to `protect_reads=True` to lock them); **writes**
(`POST /api/event`, admin) require a valid token/session, allowed Origin, and the
`admin` scope.

---

## Tests
`tests/test_mission_control.py` (15) — 7 panels present, 3D goal/knowledge panels,
agent-team M11-ready, resources, security center, event stream, health, authenticated
server (HUD + headers + open read + write-requires-auth + foreign-origin blocked).
`tests/test_resilience.py` (9) — `safe_call`, cockpit survives one/all subsystems
exploding, panel isolation, resource-monitor degradation.
