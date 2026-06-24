# FRIDAY — Verified State (Phase 0 Truth Report)

**Purpose:** Establish architectural ground truth before any code changes. No new features are proposed here.
**Method:** Every claim below was read directly from source. Each item is tagged:

- **`VERIFIED`** — read in the code; line references given.
- **`INFERRED`** — strongly implied by code/docstrings but not 100% provable without runtime tracing.
- **`PLANNED`** — described in docstrings/CLAUDE.md/naming as intent, but **not active** in the running pipeline.

**Files read line-by-line for this report:** `friday_spine.py`, `friday_app.py`, `friday_brain.py`, `friday_neural.py` (full pipeline incl. lines 300–569), `friday_local.py`, `friday_world.py` (head), `friday_chronicle.py`, `friday_signal.py`, `friday_face.py`, `friday_action.py`, `friday_codex_agent.py`, `friday_psyche.py`, `friday_sovereign.py`, `friday_config.json`. Cross-wiring confirmed by grep.

---

## ⚠️ Headline Truths (read first)

These five facts override several optimistic claims in the older docs:

1. **`VERIFIED` — The real pipeline lives in `friday_neural.think_with_context`, not `friday_brain`.** `friday_brain.respond` orchestrates signals + context packet + critic, but the actual chain (world → memory → psyche → empath → local-first → save → mood → sovereign → visual) is all inside `think_with_context` (`friday_neural.py:381–496`). The brain is a thin wrapper around it.

2. **`VERIFIED` — Sovereign's live extraction call is broken.** `think_with_context` calls `extract_and_store(user_input, response)` (`friday_neural.py:489`) but the function signature requires `(user_input, friday_response, intent, used_api=True)` (`friday_sovereign.py:187`). The call is missing `intent` → raises `TypeError` → silently swallowed by the surrounding `except` (`:490`). *However*, `friday_brain._sovereign_extract` separately calls `run_background(...)` with the correct signature (`friday_brain.py:286–292`), so extraction **does** run on the brain path — just not on the neural-only path. Net: extraction works **only because the brain double-invokes it**; the neural-path call is dead code.

3. **`VERIFIED` — The "independence %" metric is structurally stuck.** Every sovereign invocation on the live path passes `used_api=True` (`friday_brain.py:291`, and the default). Nothing ever passes `used_api=False`, even when `friday_local` answers locally. So `self_answered` never increments and `independence_pct` (`friday_sovereign.py:71`) can only ever report ~0%. The "80% self-sufficient" goal is **unmeasurable as built**.

4. **`VERIFIED` — The async event bus is never started, so all `emit_sync`/`emit_threadsafe` events are dead.** `friday_spine.boot` calls `get_bus()` and subscribes handlers (`friday_spine.py:46–47, 161–163`) but never starts the dispatch loop (`EventBus.start` at `friday_signal.py:212` is never awaited anywhere outside the module self-test). Every `emit_sync` (brain stages, neural `_emit_notice`/`THINKING_DONE`) enqueues to a queue nothing drains. **Consequence:** the `THINKING_DONE → speak` and `ACTION_EXECUTE → action` wirings in spine are inert; live paths work only because they call `brain.respond()` / `voice.say()` / etc. **directly**.

5. **`VERIFIED` — `FridayAction` is fully built but not wired to reasoning.** The brain/neural pipeline never invokes `FridayAction.execute`; there is no tool-call parsing of model output. Action is reachable only via the dead `ACTION_EXECUTE` bus handler and via gesture/window shortcuts. The 30+ system capabilities exist but FRIDAY cannot *decide* to use them in conversation.

---

## 1. Event Bus (`core/infra/friday_signal.py`)

### What currently exists
- `VERIFIED` A complete async pub/sub `EventBus`: `Signal` enum of 24 event types (`:21–56`), priority `asyncio.PriorityQueue` (`:103`), concurrent isolated handler dispatch with per-handler error isolation (`:172–190`), wildcard subscribers, `wait_for` request/response (`:230`), dead-letter/`stats` counters, `@listen` decorator, global singleton `get_bus()` (`:262`).
- `VERIFIED` Two emit paths: async `emit` (`:132`) and `emit_sync` for thread/sync callers (`:149–168`).

### What actually works
- `VERIFIED` The bus **class** works in isolation — its own `__main__` self-test starts a loop and dispatches correctly (`:304–337`).

### What is partially implemented
- `VERIFIED` `emit_sync` (`:149`) uses `asyncio.get_event_loop()` from arbitrary threads; with no running global loop it either spins a throwaway loop or schedules onto a loop nobody runs. Fragile by construction.

### What is planned but not active
- `VERIFIED` The entire **event-driven runtime**. In production boot the dispatch loop is never started, so emitted events are never consumed. All current inter-module communication is actually **direct function calls**, not events.

### What should be preserved
- The `Signal` taxonomy and the handler-isolation design — they are good and reusable.

### What should be replaced
- The lifecycle/threading model: one owned event loop on a dedicated thread + a correct `run_coroutine_threadsafe` bridge, **or** delete the bus and keep explicit calls. The current in-between state is the worst option.

---

## 2. Chronicle Memory (`core/knowledge/friday_chronicle.py`)

### What currently exists
- `VERIFIED` SQLite store with 4 tables: `memories`, `facts`, `preferences`, `sessions` (`:80–129`), WAL + indices. `MemoryType` taxonomy (`:33–40`). FAISS `IndexFlatL2(384)` semantic index (`:173`) with `all-MiniLM-L6-v2` embeddings (`:149`). Write APIs (`save_turn`, `save_fact`, `save_preference`), read APIs (`search_neural`, `search_keyword`, `get_recent`, `get_facts`, `get_preferences`), and `build_context_block` (`:493`).

### What actually works
- `VERIFIED` Turn persistence is **live**: `think_with_context` calls `save_turn("user"...)`/`save_turn("friday"...)` (`friday_neural.py:468–469`). Memories *are* being written.
- `VERIFIED` Context assembly is **live**: `build_context_block(user_input)` is called every turn (`friday_neural.py:414`) and feeds the model. Recall is real.
- `VERIFIED` FAISS→keyword graceful fallback works when embeddings/faiss are missing (`:345–346`).

### What is partially implemented
- `VERIFIED` Durability of the vector index: persisted only every 20 inserts (`:289–290`); the FAISS↔SQLite link is a side list `_embed_ids` saved to `.npy` (`:191–200`). A crash between insert and save desyncs recall permanently. The `memories.embed_id` column exists (`:91`) but is **never written** — the robust path is built into the schema but unused.
- `VERIFIED` Concurrency: `_conn_lock` is declared (`:66`) but **never acquired**; a single shared connection (`check_same_thread=False`, `:58`) is used from multiple threads (FAISS indexing thread, sovereign daemon, Flask job threads).
- `VERIFIED` Embedding truncates content to 512 chars (`:188`); long turns are partially represented in semantic space.

### What is planned but not active
- `VERIFIED` `chronicle.faiss` / `chronicle.embeddings.npy` paths exist (`:26–27`) and load if present; otherwise a fresh index is built in-process. No consolidation, decay, forgetting, or deletion API exists.

### What should be preserved
- The schema shape (episodic + facts + preferences + sessions), the keyword fallback, and `build_context_block`'s tiered assembly idea.

### What should be replaced
- The vector layer (brute-force `IndexFlatL2` → ANN, keyed by an in-row id), the save-every-20 side list, and the single-connection/no-lock concurrency model.

---

## 3. Action System (`core/io/friday_action.py`)

### What currently exists
- `VERIFIED` `FridayAction` with a 30+ command dispatch table (`:60–95`): app open/close, window focus/min/max, keyboard/mouse, screenshot, volume/mute (pycaw + nircmd fallback), brightness, URLs, **arbitrary shell** (`run_shell`, `:259`), clipboard, system stats, wifi/ip/internet, media keys, file search, startup-registry edits, sleep/restart. Capability probing for `pyautogui`/`pygetwindow`/`win32` (`:31–49`).

### What actually works
- `VERIFIED` `execute()` dispatch and the individual handlers are implemented and self-tested for safe cases (`:547–567`).
- `VERIFIED` `run_shell` has a denylist (`rm -rf`, `format`, `shutdown`, …) (`:263–268`).

### What is partially implemented
- `VERIFIED` Safety is denylist-only — `run_shell` still executes arbitrary commands with `shell=True` (`:270`); no allowlist, no confirmation, no permission tiers. `add_to_startup`, `restart_pc`, `sleep_pc` are unguarded beyond the denylist.
- `VERIFIED` `start_battery_alert` references `threading` (`:539`) but `threading` is **not imported** in this module → calling it raises `NameError`. Dead/broken helper.

### What is planned but not active
- `VERIFIED` Brain-driven actuation. Nothing in the reasoning pipeline parses model output into action calls. `execute` is only reachable via the (dead) `ACTION_EXECUTE` bus handler in spine (`friday_spine.py:142–151`) and gesture/window shortcuts. **FRIDAY cannot choose to act during a conversation.**

### What should be preserved
- The capability breadth and the snake_case dispatch contract — it's a near-ready skill catalog.

### What should be replaced
- The trust model (denylist → permissioned skill layer + confirmation), the missing `threading` import, and the un-wired invocation path.

---

## 4. Codex Agent (`core/agents/friday_codex_agent.py`)

### What currently exists
- `VERIFIED` A background self-check daemon: AST-parses every `core/**/*.py` (`:132–169`), flags **syntax errors** ("fix") and **bare `except:`** lines ("improvement"), and writes deduped markdown **proposals** (frontmatter + intent/why/change) to `FRIDAY_PROPOSALS_VAULT` (default `C:\VAULT\friday_proposals`, `:40`). Writes a `_self_check_report.md` health journal. Human-gated status workflow `pending→approved→rejected→applied` (`:45, 280–293`), `backup_file` before any apply (`:296–306`), and a CLI (`--once/--list/--approve/--reject`, `:310–333`).

### What actually works
- `VERIFIED` The full self-check → propose → report loop is real and side-effect-free w.r.t. live code. Dedup via signature hash works (`:90–103, 199–201`). Started by spine (`friday_spine.py:108–109`) on a 1800s interval (`:42`).
- `VERIFIED` Human review (`set_status`) and `backup_file` are implemented.

### What is partially implemented
- `VERIFIED` "Self-improvement" is currently **two lint rules** (syntax errors, bare excepts). There is no semantic/architectural analysis, no test awareness, no use of the LLM to generate proposals.
- `VERIFIED` There is **no `apply` function** — `set_status(..., "applied")` only edits frontmatter; nothing programmatically applies an approved diff. `backup_file` exists but is never called by any apply path (no apply path exists). Applying is entirely manual.

### What is planned but not active
- `VERIFIED` `propose_idea(...)` (`:212`) is a public API for "the main agent" to file ideas, but nothing in the brain/neural pipeline calls it. The agent is reactive-lint-only, not idea-driven.

### What should be preserved
- The safety model (propose-only, human-gated, dedicated vault, pre-apply backup) and the dedup/report mechanics. This is the right governance skeleton.

### What should be replaced / extended (later, not now)
- The analysis depth (lint → real review) and the missing test-gated apply path. Noted as truth only; no proposal here.

---

## 5. Sovereign (`core/knowledge/friday_sovereign.py`)

### What currently exists
- `VERIFIED` A regex-based fact/concept extractor: 5 fact patterns (`:83–99`), concept heuristics (backtick/quoted/CamelCase, `:161–182`), domain detection over keyword sets (`:102–122`), `DomainProfile` confidence growth (`:44–49`), `SovereignStats` with `independence_ratio/pct` (`:54–73`), persistence to `data/sovereign_stats.json` + `sovereign_domains.json`, and `run_background` daemon extraction (`:359–376`).

### What actually works
- `VERIFIED` Extraction logic itself works (self-test `:381–433`). On the **brain path**, `run_background(user_input, friday_response, intent, used_api=True)` is called correctly (`friday_brain.py:286–292`) → facts are persisted to Chronicle via `save_fact` (`:236–245`) and stats are written.

### What is partially implemented
- `VERIFIED` **Broken neural-path call:** `think_with_context` calls `extract_and_store(user_input, response)` with a missing `intent` arg (`friday_neural.py:489` vs signature `:187`) → `TypeError`, swallowed. Redundant and dead.
- `VERIFIED` **Independence metric is inert:** `used_api` is hardcoded `True` on the live path; `self_answered` never increments, so `independence_pct` is permanently ~0 regardless of how often `friday_local` actually answers. The metric does not measure what it claims.
- `VERIFIED` `concepts_learned` is declared and saved but never incremented anywhere (`_extract_concepts` returns concepts, but `_update_stats` never adds to `concepts_learned`).

### What is planned but not active
- `PLANNED` "80% self-sufficient within months" (`:11`) — there is no mechanism that could move the number, because the self/api signal is never set truthfully.

### What should be preserved
- The fact-triple + domain-profile model and the background, non-blocking extraction posture.

### What should be replaced / fixed
- The truthful `used_api` signal (wire it to whether `friday_local` answered), the duplicate broken call, and `concepts_learned` accounting.

---

## 6. Psyche (`core/persona/friday_psyche.py`)

### What currently exists
- `VERIFIED` Persistent identity + emotional state: `Identity` (name/version/persona "partner"/owner/traits/speaking style, `:68–82`), `EmotionalState` (mood/energy/focus/trust/curiosity/streaks/turn counts, `:52–63`), 8 moods with prompt fragments (`:28–48`), JSON persistence to `data/psyche.json`, thread-safe accessors under `_lock`.

### What actually works
- `VERIFIED` Psyche is **fully live**: `boot()` runs at brain startup (`friday_brain.py:47`); `get_identity_block()` + `get_mood_prompt()` are injected into the system prompt every turn (`friday_neural.py:504–506`); `record_turn(positive=True)` and `update_mood(infer_mood_from_context(...))` run every turn (`friday_neural.py:475–482`); `full_status()` feeds the HUD (`friday_face.py:131–136`). Persistence across reboots is real and self-tested (`:362–366`).

### What is partially implemented
- `VERIFIED` `record_turn` is **always** called with `positive=True` (`friday_neural.py:476`); there is no negative-feedback path, so trust only ever rises (`:218`). Mood inference uses `tone` passed from the brain packet, but the brain's tone may be a default — mood is driven more by `task_type`/`session_len` than by real sentiment.
- `VERIFIED` `infer_mood_from_context` takes `satvik_tone`, but `think_with_context` passes its own `tone` parameter (default `"neutral"`), **not** the Empath-derived tone computed a few lines below (`friday_neural.py:436–445` vs `:477–481`). Empath's richer signal is not feeding mood.

### What is planned but not active
- `VERIFIED` `set_trait` (dynamic personality evolution, `:267`) exists but is never called by any live code.

### What should be preserved
- Almost all of it. Psyche is the most cleanly-wired, genuinely-working subsystem. Keep the data model and the prompt-injection integration.

### What should be replaced / refined
- The feedback signal (always-positive `record_turn`) and the tone source mismatch (feed Empath's signal into mood).

---

## 7. Face / HUD (`core/io/friday_face.py` + `friday_app.py`)

### What currently exists
- `VERIFIED` Flask backend serving the cinematic HUD (`/`, `/friday_ui.{css,js}`), a rich `/api/status` snapshot (psyche/system/agents-roster/scheduler/gesture/memory-count/events, `:170–230`), async job API (`/api/command`, `/api/agents` → `job_id` → `/api/job/<id>`), SSE `/api/events` (`:446–464`), gesture endpoints (`/gesture/start|stop|status|stream`, incl. MJPEG webcam, `:468–523`), and legacy `/chat /greeting /stats /clear /status`. `friday_app.py` runs it backgrounded and wraps it in a native pywebview window (`:52–95`), with free-port selection and brain warm-up.

### What actually works
- `VERIFIED` The async job model is real: `_enqueue` spawns a worker thread, runs `brain.respond`, stores the outcome, and pushes an SSE `job_done` (`:374–391`). The HUD↔brain round-trip is live and **direct** (does not depend on the event bus).
- `VERIFIED` Gesture bridging: `on_gesture` records events, pushes SSE, and routes the `peace` gesture to a screen-scout brain query (`:332–357`).
- `VERIFIED` `status_snapshot` reads real psyche/sovereign/chronicle data.

### What is partially implemented
- `VERIFIED` The advertised mini-brain roster (`neural/local/world/codex/planner/critic/sovereign/visual/pdf`, `:64–74`) is **presentational** — `/api/agents` keyword-selects names for display, then just calls `brain.respond(task)` (`:287–329`). There is no real multi-agent execution; the "agents" are labels on a single pipeline call.
- `VERIFIED` `_jobs` dict grows unbounded (`:56`) — no TTL/eviction.
- `VERIFIED` No auth: `SECRET_KEY` is a hardcoded constant (`:368`), `auth_required` absent; any local process can POST `/api/command` and drive the brain (and, once actions are wired, the machine).

### What is planned but not active
- `INFERRED` The roster implies a multi-specialist execution engine that does not exist yet.

### What should be preserved
- The job/SSE architecture, the native-window approach, and the status snapshot. This layer is solid and the least-debt subsystem after Psyche.

### What should be replaced / hardened
- The fake multi-agent framing (make it real or relabel), `_jobs` eviction, and the missing local-surface auth.

---

## Cross-System Wiring Map (verified)

```
friday_app / friday_spine
        │ (direct call, NOT via bus)
        ▼
friday_brain.respond ──► friday_context.build (packet)
        │
        ▼
friday_neural.think_with_context   ◄── THE REAL PIPELINE
        ├─ world.query_world()              [live]
        ├─ chronicle.build_context_block()  [live]
        ├─ psyche.get_identity_block/mood   [live, injected]
        ├─ empath.analyze()                 [live → temp/tokens/tone]
        ├─ think(allow_local=True)
        │     └─ friday_local.answer()      [live, local-first]
        │           └─ else Groq→Gemini→OpenAI
        ├─ visual.maybe_show()              [live, best-effort]
        ├─ chronicle.save_turn() x2         [live]
        ├─ psyche.record_turn + update_mood [live, always-positive]
        └─ sovereign.extract_and_store()    [DEAD — wrong signature]
        ▼
friday_brain: critic.critique_with_retry() [live]
        ├─ learning.record_feedback()       [live]
        └─ sovereign.run_background()        [live, used_api=True hardcoded]

EventBus (emit_sync / THINKING_DONE / ACTION_EXECUTE / UI_UPDATE) ──► /dev/null
        (loop never started; all emissions dropped)

FridayAction.execute ──► only via dead ACTION_EXECUTE handler + gestures
```

---

## Summary Table

| System | Built | Live in pipeline | Key defect (verified) | Verdict |
|---|---|---|---|---|
| Event Bus | ✅ full | ❌ never started | loop not run; emit_sync fragile | **Replace lifecycle** |
| Chronicle | ✅ full | ✅ save + recall live | brute-force FAISS, save-every-20, unused lock, unused `embed_id` | **Preserve schema, replace vector/concurrency** |
| Action | ✅ 30+ cmds | ❌ not brain-driven | denylist-only; missing `threading` import; un-wired | **Preserve catalog, replace trust+wiring** |
| Codex Agent | ✅ lint+propose | ✅ runs 24/7 | only 2 lint rules; no apply path | **Preserve governance** |
| Sovereign | ✅ extractor | ⚠️ via brain only | broken neural call; `used_api` always True; inert independence % | **Preserve model, fix signals** |
| Psyche | ✅ full | ✅ fully wired | always-positive feedback; tone source mismatch | **Preserve (best subsystem)** |
| Face/HUD | ✅ full | ✅ direct round-trip | fake multi-agent; no auth; `_jobs` leak | **Preserve architecture, harden** |

---

## What FRIDAY Really Is Today (one paragraph)

FRIDAY 3.0 is a **single-pipeline, directly-wired** local-first assistant whose real cognition is `friday_neural.think_with_context`: it grounds answers in vault knowledge + episodic memory, injects a genuinely persistent personality, tries an on-device reader before the cloud, persists every turn, and updates mood — all working. Around that core sit **three honestly-working subsystems** (Psyche, Chronicle persistence/recall, Face/HUD), **two governance-correct but shallow subsystems** (Codex agent = 2 lint rules; Sovereign = works only because the brain double-invokes it), and **two impressive-but-inert subsystems** (the Event Bus, which never runs, and the Action catalog, which the brain can't trigger). The most consequential gaps are not missing features but **broken signals**: the independence metric can't move, the event bus is decorative, sovereign's primary call throws, and the machine-control layer is unreachable from reasoning. Fixing those truthfully is Phase 0's real scope.

---

*Prepared as the Phase 0 verification report. No new components proposed — architectural truth only. Where a claim is marked `INFERRED`, runtime tracing would upgrade it to `VERIFIED`/`PLANNED`.*
