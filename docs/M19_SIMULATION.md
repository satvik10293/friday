# M19 — Predictive Cognition, Simulation & Decision Intelligence (FRIDAY V3)

> **Status:** complete (awaiting review). **Goal:** give FRIDAY the ability to *think
> before acting*. Before any significant action, the new **Simulation Brain** generates
> scenarios, predicts outcomes, forecasts cost, scores risk, evaluates + ranks candidate
> plans, and recommends the safest — then **advises** the Executive Brain, which decides.
> FRIDAY never blindly executes important actions. Additive on the M18 brain framework +
> M16 services; lives under `core/brains/simulation/` (distinct from the M11
> `core/simulation` engine). No M17/M18 functionality changed.

---

## 1. Objective

```
Observe → Understand → Predict → Simulate → Compare → Evaluate Risk →
Select Best Plan → Execute → Learn
```

The Simulation Brain owns Predict → … → Select; the Executive owns Execute; the Learning
loop closes the cycle.

## 2. Simulation Brain architecture

```
 Executive.deliberate(action)
        │  (service call)
        ▼
 ┌──────────────────── SimulationBrain (advises only — never executes) ───────────────┐
 │ ScenarioGenerator → [Predictor → Forecast → RiskEngine → DecisionEvaluator] → Comparison
 │       (N futures)      (success,   (cpu/mem/   (8-dim       (expected            (rank)
 │                         intent,     storage/    risk →       success/time/cost,
 │                         failures)   net/time)   overall)     policy, score)
 └──────────────────────────────────┬──────────────────────────────────────────────────┘
                                     │  ranked plans + recommended (safest)
                                     ▼
                          Executive Brain decides → execute / ask_user
                                     │
                                     ▼  after execution
                          report_outcome → History → Learning service + predictor calibration
```

## 3. Prediction pipeline

`PredictionEngine.predict(scenario, request) → Prediction` — likely user **intent**,
**next actions**, **success probability**, **completion**, and **failure modes**, rolled
into a **confidence**. Safer scenarios (backup / ask-user / dry-run) predict higher clean
success; destructive/external direct actions predict failure modes (data loss, disclosure).
The accuracy prior is nudged by learning feedback so predictions calibrate over time.

## 4. Scenario generation design

`ScenarioGenerator.generate(request, max_scenarios)` produces multiple candidate futures:

| Action class | Scenarios |
|---|---|
| destructive (delete/format/…) | `immediate` · `backup_then` · `ask_user` · `dry_run` |
| external (send/share/upload/…) | `direct` · `redact_then` · `ask_user` |
| generic | `direct` · `cautious` · `deferred` |

Explicit `request.options` short-circuit to one scenario each. Custom generators register
via `register(predicate, fn)` (or the PluginService) — extensible without core changes.

## 5. Risk engine design

`RiskEngine.assess(...)` scores eight dimensions — **safety, privacy, security,
reliability, performance, resource, user experience, system health** — each in [0, 1],
and rolls them into one quantitative **overall** risk (`0.6·max + 0.4·mean`) with
human-readable reasons. Mitigation tags (backup/ask_user/redact/dry_run) lower the
relevant dimensions; predicted failure modes raise reliability risk; the forecast drives
performance/resource risk.

The **DecisionEvaluator** turns prediction + forecast + risk into a full plan evaluation
(expected success/time/cost/resource, risk level, confidence, dependencies, **policy
compliance**, reasoning) and a single config-weighted composite **score**. A policy gate
flags high-risk destructive/sensitive plans lacking mitigation (they rank last).
**PlanComparison** ranks best-first and summarizes the winner + margin.

## 6. Executive integration

Additive on the M18 Executive Brain (existing methods unchanged):

- `ExecutiveBrain.deliberate(action, context?, options?)` → requests a simulation,
  receives ranked plans, and **decides**: `execute` the recommended (safest) plan, or
  `ask_user` when every plan exceeds the risk threshold. Falls back to a direct decision
  when no simulation service is wired or simulation errors (never blocks the Executive).
- `ExecutiveBrain.report_outcome(simulation_id, actual)` → feeds the actual result back
  for learning.

The Executive remains responsible for the final decision; the Simulation Brain only
advises. The Memory Brain is not bypassed (persistence flows through it).

## 7. Memory & learning feedback

`SimulationHistory` stores only **meaningful** simulations (high-success strategies,
rejections, repeated failures, frequently-selected plans) through the **Memory Brain** —
temporary simulations are not flooded into memory. `record_outcome` compares predicted vs
actual success, emits the error to the **Learning** service, nudges the predictor's
accuracy prior, and remembers repeated failures (≥3×) so FRIDAY reconsiders the approach.

## 8. Event Bus additions

`simulation.requested`, `simulation.started`, `simulation.scenario.generated`,
`simulation.scenario.compared`, `simulation.risk.calculated`,
`simulation.prediction.generated`, `simulation.plan.ranked`, `simulation.completed`,
`simulation.rejected`, `simulation.forecast.updated` — published via the RuntimeService;
documented in `events.py`.

## 9. Runtime integration

Communication is exclusively through service interfaces + the Runtime event bus +
situation reports. The Simulation Brain resolves `runtime`, `memory_brain`, and `learning`
from the M16 container; `SimulationServiceProtocol` + `ServiceName.SIMULATION` are the
public seam. No direct subsystem coupling; one-way dependencies (services/base never
import the simulation brain).

## 10. Test results

`tests/test_simulation_brain.py` (units + pipeline) and `tests/test_simulation_executive.py`
(Executive integration, learning feedback, memory persistence, service facade) — **53
tests, all passing** (distinct from the M11 `test_simulation_engine/sandbox` tests, which
are untouched). Coverage: forecast, prediction, risk, scenarios, evaluation, comparison,
the simulate pipeline (ranking/rejection/events/never-raises/disabled/incremental timeout),
`deliberate`/`report_outcome`, and the no-circular-imports / side-effect-free invariants.

## 11. Performance analysis

Benchmark (`python -m core.brains.simulation.benchmark`, CPU): **~1,080 simulations/s,
~0.93 ms/simulation**, ~3.25 scenarios each. Incremental (stops at the timeout budget),
bounded history, thread-safe, low memory — suitable for long sessions.

## 12. Known limitations

- Heuristic predictor/risk/forecast (action-semantic templates); a learned predictor /
  risk model plugs in via the strategy protocols / PluginService.
- The learning loop calibrates a scalar accuracy prior; richer per-action models are
  future work.
- Forecasts are coarse signatures, not measured profiles; wiring real resource telemetry
  (via the RuntimeService) would sharpen them.

## 13. Recommendations for M20

- **Closed-loop learning:** train the predictor/risk models on the accumulated
  `prediction_outcome` samples (Learning Brain) and A/B against the heuristic baseline.
- **Real telemetry forecasts:** feed live CPU/memory/IO from the RuntimeService into the
  Forecast Engine.
- **Plan execution + monitoring:** have the Executive execute the chosen plan through the
  Automation Brain and stream progress back for mid-flight re-simulation.
- **Counterfactual memory:** store rejected/failed plans as cautionary episodes in the
  knowledge graph to bias future scenario generation.

See `core/brains/simulation/architecture.json` for the machine-readable manifest.
