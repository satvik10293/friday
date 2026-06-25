# M10 — Agent Runtime Preparation (M11)

> Closes the architecture review's "GIL-bound, threads-not-processes" scaling risk
> and lays the foundation for M11 agent teams. New additive package
> `core/agent_runtime/`. **Tests: `tests/test_agent_runtime.py` (9).**

## Design requirement

> Agents must run in **separate processes**, not threads — true parallelism for
> CPU-bound work and crash isolation, escaping the GIL the review flagged as the
> master bottleneck.

## `core/agent_runtime/`

| Module | Role |
|---|---|
| `models.py` | `AgentSpec` (name, target, args, kwargs, timeout), `AgentResult` (ok/value/error + lifecycle metrics), `RuntimeMetrics` (aggregate). |
| `runtime.py` | `ProcessAgentRuntime` — spawns work in an OS process (`spawn` context), collects result + metrics, terminates on timeout; degrades to isolated in-process execution if spawning is unavailable. `get_agent_runtime()` singleton. |
| `tasks.py` | Reference, **picklable** task functions (echo/square/slow/boom/cpu_spin) — importable so they cross the process boundary on Windows `spawn`. M11 agents supply their own importable targets the same way. |

## Lifecycle

```
Leader → AgentSpec → spawn process → perform work → return result → terminate
```

`ProcessAgentRuntime.run(target, *args, timeout=…)` launches `target` in a child
process, waits up to `timeout`, returns an `AgentResult`. A crashing agent
(`tasks.boom`) is isolated — `ok=False`, the error captured, the parent untouched.
A hung agent (`tasks.slow` beyond `timeout`) is terminated and reported
`timed_out=True`.

## Metrics (per run + aggregate)

Per `AgentResult`: spawn_ms, lifetime_ms, cpu_ms, peak_memory_mb, exit_code,
timed_out, pid, mode. `RuntimeMetrics.snapshot()` aggregates: spawns, completions,
failures, timeouts, **completion_rate**, **failure_rate**, avg spawn/lifetime —
exactly the spawn-time / lifetime / memory / CPU / failure-rate / completion-rate
the brief asks for, and the data the Mission Control "Agent Team" panel surfaces.

## Resilience

If the OS can't spawn a process (sandbox, platform limit), the runtime catches the
failure and runs the task **in-process** (isolated try/except), reporting
`mode="in_process"` rather than failing — so M11 code paths work everywhere, with
real parallelism where the platform allows it.

## M11-readiness

The Mission Control **Agent Team** panel already consumes
`agent_runtime.snapshot()` and is marked `future: "M11"`; when agent teams land,
their leaders/sub-agents/communication fill the 3D panel while the process runtime
and its metrics are already in place.
