# FRIDAY 4.0 — M1: Runtime + Observability Spine

**Status:** ✅ Delivered (code + tests + docs). Additive only — no existing file modified; FRIDAY 3.0 still boots.
**Owner:** Runtime layer (`core/runtime/`) + Observability layer (`core/observability/`).
**Tests:** `tests/test_runtime.py`, `tests/test_observability.py` — **20/20 passing** (`python -m pytest`).

---

## 1. Why this exists (the defects it closes)

Phase 0 verification (`FRIDAY_VERIFIED_STATE.md`) proved three foundational defects:

1. **Dead event bus** — `friday_spine.boot` subscribed handlers but never started the dispatch loop; `emit_sync` could not reliably reach a loop from worker threads. Every "background" signal was a no-op.
2. **No observability** — nothing recorded *why* FRIDAY did anything.
3. **Inert independence metric** — `used_api=True` was hardcoded, so "self vs API answered" was a lie at the data layer.

M1 is the substrate that fixes all three *properly* (not patched): one real event loop, and a durable Decision Log that makes behaviour an explainable, queryable fact.

> **Architectural rule honored:** this is built as new packages alongside `core/` (strangler-fig). Nothing is ripped out yet. M2+ migrate the existing modules onto this substrate one at a time, keeping the system runnable at every step.

---

## 2. Runtime (`core/runtime/`)

### Design
- **One event loop on one dedicated daemon thread.** Created with `asyncio.new_event_loop()` and run with `run_forever()`. The loop is always running while the runtime is up.
- **Thread-pool boundary.** All blocking work (models, FAISS, subprocess, STT/TTS later) goes through `submit()` (sync callers) or `offload()` (loop callers). The loop never blocks.
- **Loop-safe bus (`bus.py`).** The root cause of the 3.0 dead bus was a `PriorityQueue` bound to the wrong loop at import time. The new bus creates its queue **lazily inside the runtime loop**, so emit and dispatch always share one loop. It reuses the 3.0 `Signal`/`Event` taxonomy so vocabulary is preserved.
- **Correct cross-thread emit.** `Runtime.emit()` bridges any thread onto the loop via `asyncio.run_coroutine_threadsafe` — the precise fix for `emit_sync`'s fragility.

### Public API
| Method | Purpose |
|---|---|
| `start(timeout)` / `stop(timeout)` | Lifecycle, idempotent, graceful drain |
| `on/off(signal, handler)` | Subscribe async handlers |
| `emit(signal, …)` | **Thread-safe** publish from any thread |
| `emit_async(signal, …)` | Publish from inside the loop |
| `wait_for(signal, timeout)` | Request/response; blocks the calling thread |
| `spawn(coro, name)` | Managed background coroutine |
| `submit(fn, …) -> Future` | Blocking fn in pool (sync caller) |
| `offload(fn, …)` (await) | Blocking fn in pool (loop caller) |
| `schedule(name, fn, every, jitter, run_immediately)` | Runtime-managed periodic job (sync or async fn) |
| `cancel_schedule(name)` | Stop a periodic job |
| `register_health(name, provider)` | Plug a subsystem into `health()` |
| `health()` / `metrics()` | Diagnostics |

### Invariants
- **Import is side-effect-free.** `get_runtime()` constructs but does not start (verified by a smoke test). Preserves the project-wide rule.
- **No unmanaged threads.** Every background unit of work has a runtime-owned home. (Enforcement: M3 adds a codex-agent lint rule that flags raw `threading.Thread(...)` creation in `core/`.)

---

## 3. Observability (`core/observability/`)

### `tracing.py`
`contextvars`-based per-turn trace. `start_trace()` opens a `Trace` (id + label + elapsed + arbitrary fields); the id follows async tasks so logs and decisions correlate.

### `decision_log.py` — the keystone
A dedicated SQLite DB (`data/decisions.db`, **separate** from chronicle to avoid contention), migration-gated via a `schema_version` table from day one. Every cognitive turn ends with one row answering the charter's six questions:

| Column | Charter question |
|---|---|
| `rationale`, `intent` | **Why** was it made? |
| `memory_used` | **What memory** was used? |
| `goals_touched` | **What goal** was involved? |
| `skills_invoked` | **What tools** were used? |
| `models_used` | **Which model** was used? |
| `confidence` | **How confident** was FRIDAY? |

Plus `route`, `latency_ms`, `cost_tokens`, `outcome`, `was_autonomous`, `source`, `ts`, `trace_id`, `turn_id`. List/dict fields are JSON-encoded and decoded on read. Thread-safe (single connection + lock; WAL).

This table is also what makes **independence truthful**: self-vs-API becomes a logged `route`, not a hardcoded constant (`test_truthful_independence_signal`).

### `logging_setup.py`
Optional JSON formatter that injects the current trace id into every log line. `configure()` is explicit (never called on import).

---

## 4. How M2+ plug in (integration plan, not yet executed)

- **M2 Memory Service** registers `rt.register_health("memory", …)`, runs consolidation via `rt.schedule("consolidate", …)`, and writes `memory_used` into each decision.
- **Brain/neural** open a trace per turn (`start_trace`) and write one `decision` row at the end — immediately retiring the hardcoded `used_api=True`.
- **Spine/face** stop spawning raw threads; HUD jobs become `rt.submit(...)`; the legacy `friday_signal` bus is retired once all emitters move to `rt.emit`.
- **Reflection (M4)** is just `rt.schedule(...)` jobs reading the Decision Log.

---

## 5. Test coverage (what's proven)

**Runtime (14):** idempotent start; recovery after stop (+ double-stop); **cross-thread emit reaches a handler** (the 3.0 regression test); handler-failure isolation; `offload` runs on a `friday-io` pool thread; `submit` future; scheduler fires repeatedly (sync + async jobs); `spawn`; `wait_for` success + timeout; health/metrics shape; health provider registration + error containment.

**Observability (6):** trace id uniqueness; trace context round-trip; decision round-trip with JSON fields; the truthful-independence use case; durable reopen; stats.

**Failure/recovery classes covered:** dead-loop regression, handler crash isolation, health-provider crash containment, post-stop state, DB reopen durability.

---

## 6. Known follow-ups (tracked, not gold-plated in M1)

- `wait_for` adds a transient subscription per call — fine at current rates; revisit if used in hot loops.
- Decision Log uses one locked connection (correct for current volume); move to a small pool if write rate climbs.
- A `purge(before_ts)` / retention policy for the Decision Log lands with M4 Reflection (consolidation owner).
- **Install Git before M2** — M2 modifies `friday_chronicle`; we want real VCS history, not just additive safety.

---

*M1 delivered per the 4.0 charter: observable, testable, modular, scalable, replaceable, documented — with clear ownership, public API, lifecycle, error handling, logging, and diagnostics.*
