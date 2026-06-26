# M12 — Intelligence Operating System

> Strangler-fig, **completely additive**. No M1–M11 file was modified. New package
> `core/intelligence/` (18 modules + plugins). **Test status: 753 passed**
> (M1–M11 651 · **M12 102**). 100% local-first, no cloud dependency, no external AI
> required for primary intelligence. M12 **passed its own Design Challenge Gate**
> before implementation.

M12 gives FRIDAY's agent society (M11) a true brain: a **model-agnostic Intelligence
Operating System** where a router sends every request to a *team* of collaborating
local models. FRIDAY never depends on OpenAI/Claude/Gemini for her primary
intelligence — cloud models are opt-in plugins behind the same protocol.

---

## Design philosophy — think like an engineering team

```
Research model → Planning model → (task model) → Critic model → Executive synthesis
```

No single model dominates; every model contributes. With zero external dependencies,
the always-available **builtin local team** (reasoner, research, planner, coder,
math, memory) provides this collaboration deterministically; heavier models
(flan-t5) and cloud plugins slot in behind the same `Model` protocol when present.

---

## Architecture (18 modules)

```
                          ┌──────────────── IntelligenceOS.think() ───────────────┐
                          │                                                       │
   prompt ──► ContextBuilder ──► Router ──► ReasoningEngine ──► Critic+Confidence │
                  (Part 4)      (Part 1)       (Part 5)          (Parts 6, 8)      │
                          │         │              │                              │
                          │    Registry(2)   ExecutionManager ──► Models (plugins)│
                          │   ranks models    (retry/cache/health)   (builtin/...) │
                          │         │              │                              │
                          └──► TraceManager(11) ◄──┴──► Reflection(9) + Learning(10)
                                    │                         │
                              data/intelligence.db      secure knowledge API (M7)
```

| Module | Part | Role |
|---|---|---|
| `base.py` | — | `TaskType` (16), `Model` protocol, `BaseModel`, `ModelInfo`, `InferenceRequest/Result`. |
| `builtin_models.py` + `plugins/flan_t5.py` | 3 | Always-available local team + optional lazy flan-t5 plugin. |
| `router.py` | 1, 3 | **The heart.** Classify task + complexity → choose strategy + models → route → retry backup → structured `RouterResponse`. Sub-second. |
| `registry.py` | 2 | Runtime model roster; register by capability, hot load/unload, live stats, persisted snapshot. |
| `model_loader.py` / `model_manager.py` | 2, 3, 12 | Hot loading; bootstrap team + optional plugins; memory accounting; restart unhealthy. |
| `context_builder.py` | 4 | Gather memories/knowledge/goals/projects/prefs/agents/sims → compress to budget → **primitives only**. |
| `reasoning_engine.py` | 5 | chain-of-thought · tree-of-thought · consensus · debate · self-correction · parallel · recursive · **collaborate** (the team). |
| `critic.py` | 6 | Logic/hallucination/conflict/missing-info/weak-argument/overconfidence review → suggestions + confidence delta. |
| `planner.py` | 7 | Goal → executable plan (break/estimate/dispatch to M11 society/monitor). |
| `confidence_engine.py` | 8 | 0–100% from knowledge·memory·agreement·past-accuracy·depth·simulation. |
| `reflection_engine.py` | 9 | Review each task → distil a lesson → store via secure knowledge API. |
| `learning_engine.py` | 10 | Convert experience (projects/failures/sims/research/benchmarks/feedback) → permanent knowledge. |
| `trace_manager.py` | 11 | Record every reasoning session; searchable. |
| `execution_manager.py` | 3, 12, 14 | Single-model run with cache + health + stats; task-level execute with **backup fallback**. |
| `health_monitor.py` | 12 | Per-model latency/failure + system CPU/RAM/GPU/temp; declare unhealthy → restart. |
| `benchmark.py` | 13 | Deterministic suites, score, **rank** models. |
| `cache.py` | 14 | Bounded thread-safe LRU; hit/miss stats. |
| `optimizer.py` | 15, 17 | Find bottlenecks; auto-tune internal resources; **production changes require approval**. |
| `service.py` | 16 | `IntelligenceOS` facade + `think()` + `think_async()`; `get_intelligence_os()`. |
| `dashboard.py` | 16 | Live intelligence panel data for Mission Control. |

---

## `think()` sequence

```
think(prompt)
  1. ContextBuilder.build(prompt)         # memories+knowledge+goals+… → compressed dict
  2. TraceManager.start(goal, task)
  3. Router.route(prompt, context)
       a. classify → (task, complexity)
       b. choose_strategy + select_models (primary + backup)
       c. ReasoningEngine.reason/collaborate
            └ ExecutionManager.execute  (cache → model.infer → health → backup on fail)
       d. ConfidenceEngine + (Critic inside collaborate/self-correction)
  4. TraceManager.finish(outcome, confidence, models, ms)
  5. Reflection.reflect → lesson;  Learning.learn_from_reasoning (if confident)
  → RouterResponse {answer, confidence, models_used, strategy, trace_id, …}
```

---

## Model lifecycle

```
register → load (lazy heavy weights) → infer (timed, error-isolated) →
health.record → [unhealthy after N fails] → manager.restart → unload/unregister
```

A model is just a `Model`: `info`, `infer(request) → InferenceResult`, `health()`,
`load()/unload()`. `BaseModel` provides timing + error isolation; subclasses
implement `_run(request) → (text, structured, confidence)`.

---

## Security boundary (Part 18)

Models receive **only** an `InferenceRequest` — task, prompt, a read-only context
**dict of primitives**, and decoding params. They hold no references to FRIDAY's
stores or services, so a model **cannot** modify memory/goals/knowledge, execute
commands, or read secrets. Every state change (reflection→knowledge,
learning→knowledge) flows through the **secure service APIs** the IOS calls itself.
Tested: the gathered context is JSON-serialisable (no live objects leak) and no
registered model holds a `conn`/`remember_knowledge`/`create_goal` reference.

---

## Examples (developer guide)

```python
from core.intelligence import get_intelligence_os

ios = get_intelligence_os(knowledge_service=ks, goal_service=gs, memory_service=ms)

ios.think("compute 2 + 3 * 4").answer                 # "2 + 3 * 4 = 14"  (→ friday-math)
ios.think("debug this", task="coding",
          context={"code": "x == None"}).structured   # {'issues': ["use 'is None'…"]}
ios.think("compare and explain multiple designs",
          collaborate=True)                           # research→plan→worker→critic team
await ios.think_async("…")                            # concurrent (1000s of requests)

ios.plan("ship a web app with auth")                  # Plan(steps, estimates)
ios.benchmark_all()["ranking"]                        # rank local models
ios.optimize()                                        # bottlenecks + safe auto-tune
ios.dashboard()                                       # Mission Control panel data
```

### Adding a model (plugin architecture — no redesign)

```python
from core.intelligence.base import BaseModel, ModelInfo, TaskType

class MyModel(BaseModel):
    def __init__(self):
        super().__init__(ModelInfo(name="my-model",
            capabilities={TaskType.RESEARCH.value}, avg_accuracy=0.8))
    def _run(self, request):
        return ("answer", {"detail": ...}, 0.8)

ios.models.load_plugin(MyModel())     # hot-registered; router uses it immediately
```

Cloud models follow the same protocol but stay **opt-in** — the loader never
auto-loads them; local-first is the default.

---

## Future extension guide

- **Vision/Speech/OCR (M18+):** register vision/speech models with the matching
  `TaskType` capability — the router and dashboard already account for them.
- **Heavier local LLMs:** drop a `BaseModel` plugin (like `plugins/flan_t5.py`);
  `discover_optional()` loads it when its dependency is present.
- **Schema growth:** evolve `data/intelligence.db` via the M10 migration runner.
- **Mission Control:** mount `ios.dashboard()` as the "intelligence" panel.

---

## Performance & standards

Sub-second routing (classify + O(1) registry lookup); LRU cache avoids recompute;
async `think_async` + `reasoning.parallel` for concurrent requests (stress-tested at
40 concurrent `think` + 50 parallel reasoning); lazy model loading; CPU-only
fallback always works. Strict typing, dataclasses, dependency injection, plugin
architecture, comprehensive logging, no placeholders/TODOs — every module
production-ready and side-effect-free to import.

---

## Tests (102)

`test_intelligence_router` (11) · `test_intelligence_registry` (9) ·
`test_reasoning_engine` (10) · `test_confidence_critic` (10) · `test_context_builder`
(6) · `test_intelligence_models` (13) · `test_trace_execution` (7) ·
`test_health_benchmark` (10) · `test_cache_optimizer` (11) · `test_intelligence_os`
(15) — including the **security boundary** (models hold no services; context is
primitives-only) and **concurrency stress** (40 concurrent + 50 parallel).
