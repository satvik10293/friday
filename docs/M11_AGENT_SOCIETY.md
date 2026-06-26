# M11 — Distributed Agent Society

> Strangler-fig, **completely additive**. No M1–M10 file was modified. New package
> `core/society/`. **Tests: `test_agent_lifecycle.py` (11) · `test_agent_scheduler.py`
> (7) · `test_agent_reputation.py` (7).** Reuses the M10 process runtime — agents
> run in real OS processes.

FRIDAY becomes a *society* of specialized agents that collaborate to solve problems,
rather than one monolith answering alone.

---

## Hierarchy

```
   Executive Brain          decides: prioritise · approve · allocate (never works)
        │
   Passive Brain Coordinator  manages: spawn · schedule · monitor · merge · destroy
        │                      and is the ONLY communication relay
   Leader Agents (8, permanent)  own a domain · decompose tasks into worker subtasks
        │
   Worker Agents (temporary)     do the heavy work in separate processes · disposable
```

- **Executive** (`AgentSociety.prioritize/approve`) — decides, never performs heavy
  work.
- **Passive Brain Coordinator** (`coordinator.py`) — the management layer: spawns
  workers, schedules their work, monitors health, merges results, destroys workers,
  and relays all messages.
- **Leaders** (`leaders.py`) — 8 permanent: Research, Coding, Planning, Knowledge,
  Security, Creative, Automation, Simulation. Each `decompose()`s a task into worker
  subtasks. **Only leaders create workers.**
- **Workers** (`workers.py` + `worker_tasks.py`) — disposable specialists (Python
  Debugger, Architecture Reviewer, API Researcher, Scientific Researcher,
  Documentation Writer, Dependency Analyzer, Math Solver, Simulation Evaluator).
  Picklable pure functions — **workers never spawn workers** (they structurally
  can't reach the coordinator).

---

## Worker lifecycle (owned by the Coordinator)

```
task → select leader → decompose → spawn workers → parallel work (process runtime)
     → validate → merge results → destroy workers → update reputation
```

`AgentSociety.solve(description, domain=…, payload=…)` runs the whole lifecycle and
returns a `TaskResult` (merged outputs + per-worker results + spawn/destroy counts).
Verified: a coding task spawns 2 workers (debugger + architecture reviewer), runs
them in parallel, merges, and destroys both (0 active afterward).

---

## Communication (Part 2)

All messages route **agent → passive_brain → agent** via `AgentBus.relay`. Direct
agent→agent messaging is forbidden — `bus.deliver_direct(worker, worker)` raises
`DirectMessageError`; only hops involving the coordinator are allowed. This keeps
behaviour observable and prevents an uncontrolled agent mesh (and the O(n²) traffic
the architecture review warned about).

---

## Reputation (Part 3)

`ReputationSystem` (`reputation.py`) folds every worker run into its template's
running scores — **accuracy · reliability · speed · resource efficiency · task
success rate** — combined (weighted) into one 0..1 score (EWMA + exact success
rate). Templates above the threshold become **preferred** (the Coordinator's
first choice). Persisted in `data/society.db`.

---

## Scheduling & execution

`AgentScheduler` (`scheduler.py`) dispatches subtasks **in parallel** (bounded by
`max_parallel`) through the **M10 `ProcessAgentRuntime`** — each worker runs in its
own process by default (true parallelism, crash isolation), resolving the subtask's
target name to its picklable function. A failing worker is isolated; the batch still
returns. Order is preserved.

---

## Persistence & safety

`data/society.db` (per-thread + WAL + schema_version): agents, lifecycle events,
task history, reputation. Side-effect-free import. Distributed problem solving is
local and observable end to end.
