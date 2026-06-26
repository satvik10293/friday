# M11 — Cognitive Simulation Engine

> Strangler-fig, **completely additive**. New package `core/simulation/`. **Tests:
> `test_simulation_engine.py` (9) · `test_simulation_sandbox.py` (7) ·
> `test_virtual_agents.py` (6).**

Lets FRIDAY *simulate* solutions before recommending them — the **observe → analyze
→ simulate → evaluate → present** philosophy. Hard questions are explored in a
sandbox first, then answered with simulated evidence.

---

## Workflow

```
Problem → Simulation Director → Scenario Builder → (agent team) → Execution
        → Result Analysis → Recommendation
```

`SimulationService.simulate(problem)` is the one-shot entry point:
`director.direct()` picks a simulation type from the problem, builds a scenario,
runs it stepwise in an isolated sandbox, and attaches a `Recommendation` (text +
confidence + evidence).

---

## Simulation types (10)

architecture · software_design · research · project_planning · goal_achievement ·
**agent_society** · business · learning · scientific · custom.

### The marquee case — "Will this scale to 10,000 agents?"
The `agent_society` engine ramps virtual agents toward a target, **discovers the
failure point** (when load exceeds capacity), then **optimises** (scale-out raises
capacity) and re-evaluates. It models agent counts *analytically* so it can reason
about 100k agents while only materialising a bounded representative sample in the
sandbox (LOD by design). Output: a verdict (scales / marginal / fails) with the
discovered findings as evidence.

---

## Interactivity (Part 6) & Timeline (Part 8)

Every run records a **snapshot + metrics per step**, so playback is instant (no
recompute):

- **`SimulationControls`** — pause · resume · fast-forward · rewind · goto · replay
  · restart.
- **`Timeline`** — past / present / **predicted future** (linear extrapolation of
  the latest metrics, clearly marked predicted, never persisted).
- **`SimulationService.fork(sim, at_step)`** — branch a new simulation from any
  point (parent linked); independent thereafter.
- **`SimulationService.compare(a, b)`** — diff two runs' final metrics +
  recommendations.

---

## Sandbox isolation (Parts 9 & 13) — the safety boundary

`SimulationSandbox` is a self-contained virtual world: virtual agents / goals /
knowledge / tasks, **in memory only**. It **refuses production objects** — anything
exposing a store / `conn` / DB / known production method (e.g. `remember_knowledge`,
`create_goal`, `execute`) raises `SandboxViolation`. Only the `Virtual*` dataclasses
are admitted. `assert_isolated()` proves no production reference is held.

Verified end-to-end: running simulations leaves a real `KnowledgeService` **exactly
unchanged** — simulations can never read or modify production databases, goals,
memories, knowledge, or user data. Each simulation gets an independent virtual world.

---

## Persistence

`data/simulation.db` stores lightweight metadata (id, type, status, recommendation,
parent) with schema_version + WAL; the virtual worlds themselves stay in memory,
sandboxed. `get_simulation_service()` singleton. Side-effect-free import.
