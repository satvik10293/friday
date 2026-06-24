# FRIDAY — Architecture Review & Long-Term Evolution Plan

**Prepared by:** Chief Architect / Principal Engineer (permanent team member)
**Date:** 2026-06-23
**Scope:** Complete review of FRIDAY 3.0, grounded in the source tree, with a multi-year evolution proposal (4.0 / 5.0).
**Status of evidence:** Findings tagged **[verified]** were read directly from source; **[inferred]** are drawn from `CLAUDE.md`, docstrings, and the mini-brain roster and should be confirmed before acting.

---

## 0c. Phase 0 Delivery Wrap-up (reply, verbatim)

Done. Two outputs:

### 1. `FRIDAY_VERIFIED_STATE.md` (the Phase 0 deliverable)
A source-backed truth report covering all 7 systems, with every claim tagged **`VERIFIED`** (line-cited), **`INFERRED`**, or **`PLANNED`**, and each system broken into *exists / works / partial / planned-not-active / preserve / replace*. It includes a cross-system wiring map, a summary table, and a one-paragraph "what FRIDAY really is today."

### 2. Appended the reply verbatim into `FRIDAY_ARCHITECTURE_REVIEW.md`
As a new **Section 0b**, keeping your running-log pattern.

### The five headline truths the verification uncovered
Reading the actual code (not just docstrings) overturned several optimistic claims:

1. **The real pipeline is `friday_neural.think_with_context`, not `friday_brain`** — the brain is a thin wrapper around it.
2. **Sovereign's live extraction call throws** — `extract_and_store(user_input, response)` is missing the required `intent` arg (`friday_neural.py:489` vs signature `friday_sovereign.py:187`); it's silently swallowed. It only runs at all because the brain *separately* calls `run_background(...)` correctly.
3. **The "independence %" metric is structurally stuck at ~0** — `used_api=True` is hardcoded on every live path; `self_answered` never increments, so "80% self-sufficient" is unmeasurable as built.
4. **The event bus is never started** — all `emit_sync` events drop into a queue nobody drains; the `THINKING_DONE→speak` and `ACTION_EXECUTE→action` wirings are inert.
5. **`FridayAction` (30+ commands) is built but unreachable from reasoning** — no tool-call parsing exists; FRIDAY can't choose to act mid-conversation. (Bonus bug: `start_battery_alert` uses `threading` without importing it → `NameError`.)

### What this corrected from my earlier review
My architecture review had marked Psyche, Sovereign, Action, and Codex internals as **[inferred]**. Now verified:
- **Psyche** is actually the *best-wired* subsystem (fully live, persistent, injected every turn) — better than I'd credited.
- **Sovereign** and **Action** are *worse* than the roster implied — one throws on its primary call, the other is unreachable.
- **Codex agent** is governance-correct but shallow (two lint rules, no apply path).

The headline for Phase 0: FRIDAY's real problems aren't missing features — they're **broken signals** in code that looks finished. That's the honest scope before any 4.0 work begins.

---

## 0b. Phase 0 Verification Handoff (reply, verbatim)

I read all seven systems line-by-line (plus the neural pipeline that actually drives them) and wrote the full report to **`FRIDAY_VERIFIED_STATE.md`**, structured as `VERIFIED` / `INFERRED` / `PLANNED` per system with line references. The verification overturned several optimistic claims — here are the truths that matter most:

**1. The real pipeline is `friday_neural.think_with_context`, not `friday_brain`.** The brain is a thin wrapper; the actual chain (world → memory → psyche → empath → local-first → save → mood → sovereign → visual) all lives in neural (`friday_neural.py:381–496`).

**2. Sovereign's live extraction call is broken.** `think_with_context` calls `extract_and_store(user_input, response)` (`:489`) but the signature needs `(user_input, friday_response, intent, used_api=True)` → `TypeError`, silently swallowed. It only works at all because `friday_brain._sovereign_extract` *separately* calls `run_background(...)` with the correct args. The neural-path call is dead.

**3. The "independence %" metric is structurally stuck at ~0.** Every live sovereign call passes `used_api=True`; nothing ever passes `used_api=False`, even when `friday_local` answers locally. `self_answered` never increments. The "80% self-sufficient" goal is unmeasurable as built.

**4. The event bus is never started — all `emit_sync` events are dropped.** `friday_spine.boot` subscribes handlers but never runs the dispatch loop. The `THINKING_DONE → speak` and `ACTION_EXECUTE → action` wirings are inert; everything works only via direct calls.

**5. `FridayAction` (30+ commands) is built but the brain can't trigger it.** No tool-call parsing exists; `execute` is reachable only via the dead bus handler and gestures. FRIDAY cannot choose to act mid-conversation. (Also: `start_battery_alert` references `threading` without importing it → `NameError`.)

**What's genuinely healthy:** Psyche is the best-wired subsystem (persistent identity + mood, injected into every prompt, updated every turn — all live). Chronicle's save + recall are live (turns are persisted and `build_context_block` feeds every turn). Face/HUD's job/SSE round-trip is solid and direct.

**What's shallow-but-correct:** the Codex agent runs 24/7 but is only two lint rules (syntax errors + bare excepts) with no programmatic apply path; Sovereign's model is fine but its signals are untruthful.

**Per-system verdicts (preserve/replace):**
- Event Bus — preserve the `Signal` taxonomy + handler isolation; replace the lifecycle (run one loop or delete it).
- Chronicle — preserve schema + keyword fallback; replace brute-force `IndexFlatL2`, the save-every-20 side-list, and the single-connection/unused-`_conn_lock` concurrency.
- Action — preserve the command catalog; replace the denylist-only trust model and wire it to reasoning; fix the missing `threading` import.
- Codex Agent — preserve the propose-only/human-gated/backup governance; (later) deepen analysis + add test-gated apply.
- Sovereign — preserve the fact-triple + domain model; fix `used_api`, the duplicate broken call, and `concepts_learned` accounting.
- Psyche — preserve almost everything; refine the always-positive feedback and feed Empath's tone into mood.
- Face/HUD — preserve job/SSE + native window; harden auth, evict `_jobs`, make the multi-agent roster real or relabel it.

Bottom line: FRIDAY's biggest issues today aren't missing features — they're **broken signals** (dead bus, inert independence metric, throwing sovereign call, unreachable action layer). Fixing those truthfully is the real scope of Phase 0. Full detail with line citations is in `FRIDAY_VERIFIED_STATE.md`.

---

## 0. Review Handoff (reply, verbatim)

The full review is written to **`FRIDAY_ARCHITECTURE_REVIEW.md`** — all 38 sections, grounded in source I actually read (each claim tagged **[verified]** or **[inferred]**). Here's the executive summary and the parts you should act on first.

## The two findings that matter most

**1. FRIDAY's nervous system isn't running.** `friday_spine.boot()` creates the `EventBus` and subscribes handlers, but never calls `bus.start()` — the async dispatch loop never runs. And `EventBus.emit_sync` tries to reach a loop via `asyncio.get_event_loop()` from worker threads, which can't reliably work. The system only functions because the voice loop and HUD call `brain.respond()` *directly*, bypassing the bus entirely. So the elegant pub/sub layer is currently **dead weight that implies a contract the system doesn't honor**. Every "background" handler (speak-on-`THINKING_DONE`, error-to-notify) is effectively a no-op. Fix this or remove it — don't build reactive features on top.

**2. The memory layer won't survive its own success.** `friday_chronicle` is conceptually the crown jewel but mechanically fragile:
- `faiss.IndexFlatL2(384)` — brute-force O(N) recall, won't reach "millions of memories"
- FAISS↔SQLite link is a Python side-list (`_embed_ids`) persisted **only every 20 inserts** → a crash silently desyncs recall permanently (and the `memories.embed_id` column that would fix this exists but is unused)
- one shared SQLite connection across threads with a `_conn_lock` that's **declared but never acquired**
- no forgetting/consolidation/deletion path — "remembered forever" + brute force = unbounded cost

## Other verified weaknesses
- **Two concurrency models** (sync threads in spine, Flask threads + ad-hoc daemon threads in face, an unused async bus) with no unifying policy
- **No observability** — nothing records *why* FRIDAY did anything
- **No migrations** (`CREATE TABLE IF NOT EXISTS` only) for data meant to last years
- **No tool/skill abstraction**, and `friday_action` is a confused-deputy risk (model-driven desktop actuation reachable from an unauthenticated localhost endpoint)
- **No test suite** for a system that proposes edits to itself

## The shape of the plan
- **4.0** = "make the foundation honest, then add agency": a real **Runtime** (one event loop + thread-pool), re-platformed **Memory Service**, **Decision Log**, **Skill Registry**, **Goal Engine + Mission Control**, **Reflection**, **World Model + Truth Engine**.
- **5.0** = integration depth: a continuous perceive→recall→deliberate→act→reflect **cognitive loop**, knowledge graph, multi-model orchestration, autonomy budgets.
- **Roadmap** gates it: **Phase 0 (stabilize) and Phase 1 (runtime + observability + tests) before any new feature.** Building goals/reflection/perception on the current unrun bus would just multiply the trap.

The doc includes proposed DB schemas, event-flow and UML diagrams, the target folder structure, and runnable code skeletons for the Runtime (with a correct `emit_threadsafe`), Decision Log, Skill registry, Memory Service (atomic `embed_id` + rebuildable index), and Goal Engine.

One caveat I want to flag honestly: the persona, sovereign, codex-agent, and action internals are marked **[inferred]** — I reviewed their roles from `CLAUDE.md` and the roster but didn't read those files line-by-line. Want me to do a verification pass on `friday_psyche`, `friday_sovereign`, `friday_codex_agent`, and `friday_action` next, so the persona/security/self-improvement sections are fully source-backed before you commit to any dates?

---

## 1. Executive Summary

FRIDAY 3.0 is an unusually *coherent* hobby-scale cognitive architecture: a clean subpackage layout, a real respond pipeline, local-first reasoning with cloud fallback, persistent episodic memory with semantic search, a personality layer, a native HUD, and a human-gated self-improvement loop. The **conceptual** architecture is already close to right. The **mechanical** architecture is where the risk lives.

The single most important finding: **FRIDAY's nervous system is not actually running.** `friday_spine` wires handlers onto the async `EventBus` but never starts its dispatch loop, and `emit_sync` is invoked from worker threads in a way that cannot reliably reach that loop. The system works today only because the critical paths (voice loop, HUD jobs) call `brain.respond()` *directly* and bypass the bus. This means the elegant pub/sub design is, in practice, **dead weight and a latent correctness trap** — every "background" signal handler (speak-on-THINKING_DONE, error-to-notify) is effectively a no-op in spine mode. This must be resolved before any further event-driven features are built on top of it.

The second-most important finding: **the memory subsystem will not survive its own success.** `friday_chronicle` is the crown jewel conceptually but is built on a brute-force `IndexFlatL2`, a single unsynchronized SQLite connection, an index that persists only every 20 vectors, and an append-only id-mapping with no deletion, rebuild, or consolidation path. At thousands of memories it is fine; at the "millions of memories" target it is a guaranteed rewrite. Better to design the durable memory substrate now.

Everything else — knowledge, persona, voice, vision, tools, goals — is either solid or greenfield. The recommendations below are sequenced so that the **foundational reliability fixes (bus, memory durability, concurrency, observability)** come first, because every ambitious capability you want (goals, reflection, world model, skills) is a *consumer* of those foundations. Build the bedrock, then build the cathedral.

**Top 5 actions, in order:**
1. Decide the concurrency model (async-core vs. thread-core) and make the bus real or remove it. *(reliability, unblocks everything)*
2. Harden `friday_chronicle`: WAL + per-thread connections + atomic id-mapping + ANN index + a rebuild path. *(scalability)*
3. Add structured observability (tracing per turn, a `decisions` log). *(explainability/observability)*
4. Introduce a typed **Context Assembler** with a token budget and reranking. *(intelligence/quality)*
5. Introduce the **Tool/Skill layer** as the spine of FRIDAY 4.0. *(extensibility)*

---

## 2. Understanding of the Current System

### 2.1 Runtime shapes
There are two entry points with **different execution models** [verified]:

- **`friday_spine.py`** (voice): synchronous, thread-based. `boot()` instantiates `FridayBrain`, `FridayVoice`, `FridayAction`, `FridayNotify`, starts `friday_world`, the scheduler, the codex agent, and the proactive watcher — each guarded so failures degrade rather than crash. The voice loop is a blocking `while` that calls `senses.listen_once()` → `brain.respond()` → `say()`.
- **`friday_app.py`** (HUD): runs `friday_face` (Flask) on `127.0.0.1:7862` in a background thread, then opens a native pywebview window. HUD turns are **async jobs**: POST `/api/command` → `job_id` → poll `/api/job/<id>` / SSE.

### 2.2 The respond pipeline [verified]
`FridayBrain.respond(user_text) → str` (never raises, always returns a string):
1. emit `USER_TEXT`
2. `friday_context.build()` → packet (`intent`, `priority`, `topic`, `temperature`, `max_tokens`, `route_to`, `tone`, …) with a `SimpleNamespace` fallback
3. emit `THINKING_START`
4. route: `codex` or `planner` if present in `packet.route_to`, else `friday_neural.think_with_context()`
5. `friday_critic.critique_with_retry()`
6. emit `THINKING_DONE`
7. `friday_learning.record_feedback()`
8. `friday_sovereign.run_background()` (fact extraction)

Local-first lives **inside** `friday_neural`/`friday_local` (retrieval with `all-MiniLM-L6-v2`, reader `google/flan-t5-base`, retrieval floor 0.30); if nothing clears the floor it defers to **Groq → Gemini → OpenAI → emergency fallback**.

### 2.3 Memory [verified]
`friday_chronicle`: SQLite (`memories`, `facts`, `preferences`, `sessions`) + a FAISS `IndexFlatL2(384)`. Writes embed into FAISS inline; `build_context_block()` assembles a char-budgeted context from neural search + recent turns + facts + preferences.

### 2.4 Knowledge [verified]
`friday_world`: Obsidian vault at `C:\VAULT\satvik` (`FRIDAY_VAULT`), one note per managed entry, FAISS semantic search with keyword fallback, on-demand Wikipedia, **no background ingest loop**, user's own notes never touched (no `fact_id` frontmatter).

### 2.5 Nervous system [verified]
`friday_signal.EventBus`: async `PriorityQueue`, concurrent isolated handlers, wildcard subscribers, `wait_for`, dead-letter stats. **But the loop is never started in spine, and `emit_sync` cannot reach it reliably from threads.**

### 2.6 Persona / IO / agents / infra [inferred from roster + CLAUDE.md]
`friday_psyche` (identity/mood, `data/psyche.json`), `friday_empath` (tone); `friday_face/action/proactive/visual/notify/phone/whatsapp/gesture`; `friday_codex_agent` (24/7 proposals → `C:\VAULT\friday_proposals`); `friday_scheduler`, `friday_secrets`; voice stack (`stt/tts/voice/senses/voice_loop/audio/mic_test`).

---

## 3. Strengths Worth Preserving

1. **Subpackage seam discipline** — `brain/knowledge/persona/io/agents/infra/voice` is a genuinely good decomposition. Keep it.
2. **Side-effect-free imports** — a rare and valuable invariant; it makes testing and module CLIs possible. Protect it ruthlessly.
3. **Local-first with graceful cloud fallback** — the right intelligence/cost/privacy posture. The retrieval-floor "defer to cloud" pattern is sound.
4. **Degraded-boot philosophy** — guarded module init so one failure doesn't sink the ship. This is principal-grade thinking already present.
5. **Human-gated self-improvement** — proposals to a vault rather than auto-applied edits. Exactly right for safety.
6. **Single brain entry point** (`respond()` never raises) — a clean, testable contract.
7. **Keyword fallback everywhere FAISS is used** — the system stays useful without heavy deps.
8. **Module self-tests** (`__main__` blocks) — cheap, effective, keep expanding them.

---

## 4. Critical Weaknesses

| # | Weakness | Evidence | Severity |
|---|---|---|---|
| W1 | **Event bus never started in spine; `emit_sync` thread-fragile** | `friday_spine.boot` calls `get_bus()` but no `bus.start()`; `emit_sync` uses `get_event_loop()` from threads [verified] | **Critical** |
| W2 | **Two execution models (sync threads vs. async/Flask) with no unifying concurrency strategy** | spine vs. face [verified] | **Critical** |
| W3 | **Chronicle won't scale or stay consistent** | `IndexFlatL2`, save-every-20, single shared conn, `_conn_lock` declared but unused, no delete/rebuild [verified] | **Critical** |
| W4 | **No observability** — no per-turn trace, no decision log, no structured metrics | grep: only `logging` + print [verified] | High |
| W5 | **Context assembly is naive** — char truncation, no token budget, no reranking, no dedup | `build_context_block` [verified] | High |
| W6 | **Lazy heavy-model loading on the request path** — first turn loads MiniLM + flan-t5 synchronously | `friday_local`, `chronicle._load_embedder` [verified] | High |
| W7 | **No tool/skill abstraction** — "tool usage" is aspirational; actions are ad hoc | roster, `friday_action` [inferred] | High |
| W8 | **Config/secret duplication & shadowing risk** | neural `_pick_config_path` exists precisely to dodge an empty-template shadow [verified] | Medium |
| W9 | **No schema migrations** — `CREATE TABLE IF NOT EXISTS` only; no version, no upgrade path | chronicle `_init_schema` [verified] | Medium |
| W10 | **Knowledge & memory use *separate* FAISS indices and embedders** — duplicated cost, no unified recall | chronicle vs. world [verified] | Medium |
| W11 | **No backpressure / cancellation on jobs** — HUD jobs can't be cancelled; `_jobs` grows unbounded | `friday_face._jobs` [verified] | Medium |
| W12 | **No test suite** — only inline self-tests; no `tests/`, no CI | tree [verified] | High |

---

## 5. Technical Debt Analysis

**Structural debt (compounding):**
- **The phantom bus (W1/W2).** Every future "reactive" feature (proactive nudges, reflection triggers, goal progress events) wants an event backbone. Right now that backbone is decorative. This is *negative-value* code: it implies a contract the system doesn't honor. Either make it real (run one event loop, route everything through it) or delete it and use explicit calls. Cost of fixing now: ~1 week. Cost later: every event-driven feature inherits the trap.
- **Dual concurrency model.** Flask threads + spine threads + ad-hoc `threading.Thread(daemon=True)` + an unused async bus. Four concurrency idioms, no policy. Pick one core: I recommend **async core with a thread-pool boundary for blocking work** (models, FAISS, subprocess), exposed behind a single `Runtime`.

**Data debt:**
- **No migrations.** The day you add a column to `memories`, every existing user DB needs an upgrade path. Introduce a `schema_version` table and a migration runner *before* the schema grows.
- **FAISS/SQLite id coupling.** `_embed_ids` (a Python list saved to `.npy`) is the *only* link between FAISS row position and `memories.id`, persisted only every 20 inserts. A crash between insert and save permanently desyncs recall. This is silent data corruption waiting to happen.

**Process debt:**
- **No tests, no CI, no typing gate.** For a system meant to live years and self-modify, the absence of a regression net is the highest *long-term* risk. The codex agent proposing edits with no test suite to validate against is a correctness hazard.

**Cosmetic/known debt (cheap):** voice temp files in CWD; `friday_mic_test` records on import; historical plaintext keys (rotate).

---

## 6. Scalability Analysis

Evaluated against the stated future: *millions of memories, thousands of vault notes, multiple models, dozens of tools, years of history, multiple agents, large knowledge graphs.*

| Dimension | Today | Breaks at | Fix |
|---|---|---|---|
| Memory recall | `IndexFlatL2` brute force, 384-dim | ~10⁵–10⁶ vectors (latency seconds, RAM GBs) | ANN index (HNSW/IVF-PQ) or vector DB; quantize |
| Memory storage | One SQLite file, single conn | write contention well before millions of rows | per-thread conns, WAL (present), partition cold storage |
| Context assembly | Linear scans + char budget | grows with history; no relevance ceiling | token-budgeted assembler + reranker + summarized tiers |
| Vault search | FAISS over notes | thousands of notes OK; tens of thousands needs ANN | shared ANN substrate with memory |
| Models | Lazy singletons, one process | multiple local models = RAM pressure, no GPU | model manager + process isolation / on-demand load-unload |
| Tools | None formal | adding the 5th tool without a registry = spaghetti | Skill registry + manifest |
| Agents | Codex only, thread | multiple agents contend on DB + models | scheduler with concurrency limits + queue |

**Verdict:** the architecture is **vertically** fine for ~years of *single-user* use *if* memory and recall are re-platformed. The brute-force index is the first hard wall.

---

## 7. Reliability Analysis

- **Single points of failure:** the shared SQLite connection (W3) and the lazy model load on the request path (W6). A model download stall blocks the first turn; a DB lock blocks all writers.
- **Crash consistency:** FAISS index vs. SQLite can desync (W3). No write-ahead reconciliation; no startup integrity check.
- **Error isolation:** *good* at the bus handler level (isolated, by design) and at the brain level (`respond` never raises). *Poor* at the data level.
- **Recovery:** no self-heal for a corrupted FAISS sidecar beyond "delete and rebuild," and rebuild isn't implemented for chronicle (only `friday_local --train` rebuilds the QA index).
- **Watchdogs:** the 5-minute heartbeat exists but nothing acts on a missed heartbeat.

**Recommendations:** (a) startup integrity check that reconciles `faiss.ntotal` against `COUNT(*)` and rebuilds if drift; (b) a `health` endpoint and a supervisor that restarts dead subsystems; (c) idempotent writes with a monotonic `embed_id` stored *in the row*, not a side list.

---

## 8. Memory System Review (`friday_chronicle`)

**What's right:** episodic typing (`MemoryType`), importance field, sessions, neural+keyword recall, a context-block assembler, fact triples. The conceptual model (episodic + semantic + preference) is correct.

**What's wrong / risky [verified]:**
1. `IndexFlatL2` brute force — replace with HNSW (great recall/latency on CPU) or IVF-PQ (memory-bounded).
2. `_embed_ids` side-list persisted every 20 inserts — move the FAISS row id into the `memories` row (`embed_id` column already exists but is unused!) and persist atomically, or adopt an index that supports `add_with_ids` + `remove_ids`.
3. Single shared `sqlite3` connection across threads with an **unused** `_conn_lock` — switch to per-thread connections (or a small connection pool) with WAL (already on).
4. No **forgetting / consolidation / decay**. "Remembered forever" + brute force = unbounded cost and degrading recall precision. Add importance decay, deduplication, and periodic consolidation into summaries (see §19 Workspace Memory and §23 Reflection).
5. `content[:512]` embedding truncation silently drops long turns from semantic space.
6. No deletion / correction API — you can't forget a wrong fact. Needed for the Truth Engine (§24).

**Target memory tiers (see §19):** Working → Episodic → Semantic → Archival, with explicit promotion/demotion. Keep the SQLite source of truth; treat vectors as a derived, rebuildable index.

---

## 9. Knowledge System Review (`friday_world`)

**Strengths:** vault-as-truth, user-notes-immutable invariant, on-demand fetch (no runaway crawler), keyword fallback.

**Gaps:**
- **Two embedders, two indices** (world vs. chronicle) — duplicate RAM and no unified recall. Unify on a single embedding service and a shared vector substrate with namespaces (`memory`, `vault`, `decisions`, `skills`).
- **No graph.** "Knowledge graph" is a goal but storage is flat notes + frontmatter. Introduce an explicit entity/relation store (see §22 World Model) layered over the vault rather than replacing it.
- **No provenance/confidence on vault facts** comparable to `facts.confidence` in chronicle — needed for the Truth Engine.
- **Sync fetch on the path** (Wikipedia on demand) can stall a turn; move to async prefetch with a timeout budget.

---

## 10. Persona System Review (`friday_psyche`, `friday_empath`) [inferred]

**Concept is strong** — identity + mood + tone as first-class state injected into reasoning differentiates FRIDAY from a chatbot. **Risks to check:**
- Persona state in a single JSON (`psyche.json`) — fine now; version it and avoid lost-update races (read-modify-write from multiple threads).
- Mood should be **evidence-linked** (why did mood change?) and feed the decision log (§26), or it becomes unexplainable drift.
- Keep persona *influence* declarative (tone/temperature/word choice), not control-flow — personality should color responses, never gate correctness. (The brain already passes `tone` as a parameter — good; keep it that way.)

---

## 11. Voice & Vision System Review [verified for wiring; inferred for internals]

- **Voice:** faster-whisper STT + edge-tts TTS, interruptible sentence-by-sentence speech in spine. Good. **Issues:** temp files in CWD; `mic_test` records on import; no barge-in detection tied to the bus; STT/TTS are blocking and should live behind the thread-pool boundary.
- **Vision:** today it's **gesture control** (MediaPipe HandLandmarker) + a screen-change watcher + `friday_visual` opening maps/news/images. There is **no perception pipeline** (no OCR/scene understanding/UI-element grounding). For the stated vision capability, this is the biggest greenfield. Recommend a `core/perception/` subpackage with a frame source, a pluggable analyzer chain (OCR → element detection → VLM captioning), and an event emitter — explicitly rate-limited (the proactive watcher's "no per-frame OCR" instinct is correct; preserve it).

---

## 12. Infrastructure Review (`friday_signal`, `friday_scheduler`, `friday_secrets`)

- **Signal (W1/W2):** good design, not wired. Decision required: **async core**. Run exactly one event loop in a dedicated thread; expose `emit()` (async) and a *correct* `emit_threadsafe()` using `loop.call_soon_threadsafe`. Route the real pipeline events through it so handlers (speak, notify, UI, reflection) actually fire.
- **Scheduler:** present and used (heartbeat). Needs: concurrency limits, jitter, persistence of last-run, and integration with the goal/agent system so periodic cognition (reflection, consolidation) is first-class.
- **Secrets:** `.env` loading is correct. Add: key presence validation at boot with a clear degraded-mode message, and never log values (audit `friday_neural` logging).

---

## 13. Security Review

- **Keys:** now `.env`-based [verified]; rotate the historically exposed ones. Add a `.env` schema check.
- **Local HTTP surface:** Flask on `127.0.0.1` with `SECRET_KEY="friday-face-secret"` and `auth_required` absent. Localhost-only mitigates, but any local process / browser page can POST `/api/command` and drive FRIDAY (and `friday_action` can take desktop actions!). Add a per-session token the webview injects, and an allowlist on `friday_action`.
- **`friday_action` is a confused-deputy risk:** a model-driven desktop actuator reachable from a local HTTP endpoint. Gate destructive actions behind explicit confirmation and an action policy (see Skill permissions §25).
- **Codex self-edit path:** auto-backup is good; require the proposal to carry a diff + a test, and never apply without a green test run (ties to W12).
- **Prompt-injection via vault/web:** content fetched into context can carry instructions. Mark retrieved content as untrusted and never let it escalate to tool calls without policy checks.

---

## 14. Performance Bottlenecks

1. **First-turn latency** — synchronous load of MiniLM + flan-t5 + FAISS (W6). Mitigate with the existing brain warm-up (face does this) and a model manager that preloads on boot in the background.
2. **Brute-force vector search** (W3) — O(N·d) per recall, twice (memory + vault).
3. **Per-turn linear SQLite scans** with `LIKE %...%` (no FTS) in keyword fallback — add SQLite FTS5.
4. **Context assembly** re-embeds the query separately per subsystem — embed once, reuse.
5. **Sync web fetch** in world on the path.
6. **SSE + jobs**: `_jobs` dict never evicted; add TTL/LRU.

---

## 15. Missing Capabilities (vs. the stated vision)

| Vision item | Status | Gap |
|---|---|---|
| Personality / Identity | ✅ present | evidence-linking, versioning |
| Long-term memory | ⚠️ present but not scalable | tiers, consolidation, forgetting |
| Knowledge accumulation | ✅ vault | graph, provenance |
| Voice | ✅ | barge-in, temp-file hygiene |
| Vision | ❌ (gesture only) | perception pipeline |
| Tool usage | ❌ | **Skill system (§25)** |
| Project awareness | ❌ | **Workspace/Project model (§19/§22)** |
| Goal management | ❌ | **Goal system (§20) + Mission Control (§21)** |
| Self-reflection | ❌ | **Reflection system (§23)** |
| Self-improvement proposals | ✅ codex | needs test-gated apply |
| Local-first reasoning | ✅ | model manager |
| Human oversight | ⚠️ partial | unified approval queue + audit (§26) |
| Native HUD | ✅ | observability surfaces |
| Modular architecture | ✅ | runtime/event unification |

The four big greenfield pillars for 4.0: **Skills, Goals, Reflection, Perception** — all riding on a unified **Runtime + Memory** foundation.

---

## 16. FRIDAY 4.0 Architecture Proposal

**Theme: "Make the foundation real, then add agency."** 4.0 turns FRIDAY from a respond-pipeline into an *agent with goals and tools*, on a reliable runtime.

### 16.1 Layered architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ Presentation:  HUD (face)  ·  Voice  ·  Perception(new)             │
├─────────────────────────────────────────────────────────────────────┤
│ Cognition:  Brain · Context Assembler(new) · Planner · Critic       │
│             Reflection(new) · Goal Engine(new) · Truth Engine(new)  │
├─────────────────────────────────────────────────────────────────────┤
│ Capability:  Skill Registry(new) · Tools · Actions                  │
├─────────────────────────────────────────────────────────────────────┤
│ Knowledge & Memory:  Memory Service(re-platformed) · World Model    │
│                      · Vector Substrate(shared) · Decision Log(new) │
├─────────────────────────────────────────────────────────────────────┤
│ Runtime(new):  one event loop · thread-pool boundary · model mgr    │
│                · scheduler · secrets · health/observability         │
└─────────────────────────────────────────────────────────────────────┘
```

### 16.2 The Runtime (the keystone new component)

**Why it should exist:** to end the dual-concurrency chaos (W1/W2) and give every subsystem one place to (a) emit/handle events, (b) offload blocking work, (c) schedule periodic cognition, (d) acquire models. **Problem solved:** the phantom bus, request-path stalls, uncoordinated threads. **Alternatives:** (i) go fully synchronous and delete the bus — simplest, but forecloses reactive features; (ii) multiprocess actors — robust isolation but heavy for single-user desktop. **Tradeoff chosen:** async core + thread-pool is the sweet spot for a Python desktop app with blocking ML calls. **Integration:** `friday_spine` becomes a thin `Runtime` bootstrapper; `friday_face` submits turns as runtime tasks instead of raw threads. **Complexity:** Medium (1–2 weeks). **Maintenance:** *reduces* long-term cost by collapsing four idioms into one.

### 16.3 4.0 module deltas (see §31/§32)
Add: `runtime`, `core/memory/` (service), `core/cognition/` (context assembler, reflection, goals, truth), `core/skills/`, `core/perception/`, `core/observability/`. Refactor: chronicle → memory service; signal → runtime bus; world → world model + shared vector substrate.

---

## 17. FRIDAY 5.0 Architecture Proposal

**Theme: "Cohesive persistent intelligence."** Given 4.0's reliable runtime, memory tiers, skills, goals, and reflection, 5.0 is about **integration depth and autonomy under oversight**:

1. **Unified Cognitive Loop** (§18) replaces the linear pipeline with a perceive→recall→deliberate→act→reflect cycle that runs continuously, not only on user turns.
2. **Knowledge Graph World Model** (§22) — entities/relations as first-class, with the vault as the human-readable projection.
3. **Multi-model orchestration** — a model router that picks local vs. cloud vs. specialized (vision, code) per sub-task, with a cost/latency/quality policy.
4. **Autonomy budget** — FRIDAY pursues goals proactively within explicit, revocable budgets (time, actions, spend), every autonomous act logged to the Decision Memory (§26) and surfaced in Mission Control (§21).
5. **Federation-ready memory** — optional encrypted sync substrate so FRIDAY can span devices (the vault model makes this tractable).

5.0 is an *integration* release; resist building it before 4.0's foundations are load-bearing.

---

## 18. Cognitive Layer Design

Replace the one-shot pipeline with an explicit, observable cognitive cycle. Each stage is a pure-ish function over a `CognitiveState`, emitting trace spans.

```
            ┌──────────── perceive ───────────┐
            │ user text / voice / screen event │
            └───────────────┬─────────────────┘
                            ▼
                        recall  ──→ Memory Service (tiers) + World Model
                            ▼
                       deliberate ──→ Goal Engine (relevant goals)
                            │          Planner / Neural / Local
                            │          Truth Engine (claim check)
                            ▼
                          act  ──→ Skill Registry (tools / actions)
                            ▼
                        respond
                            ▼
                        reflect ──→ Decision Log + consolidation + learning
```

`CognitiveState` carries: input, assembled context, candidate goals, plan, chosen skills, response, and a trace id. The current `friday_brain.respond` becomes the *synchronous fast path* of this loop (perceive→recall→deliberate→respond) while reflection/consolidation run on the runtime after the turn.

---

## 19. Workspace Memory Design

**Why:** the brain needs a bounded, fast, *current* working set — what we're doing right now — distinct from long-term storage. Today's `build_context_block` conflates "everything relevant" with "what's in focus."

**Tiers:**
- **Working memory (RAM, seconds–minutes):** current task, last N turns, active goal, open files/app — the "attention buffer." Token-budgeted.
- **Episodic (SQLite, durable):** every turn/event (today's `memories`).
- **Semantic (vectors + graph):** consolidated facts/entities (today's `facts` + world).
- **Archival (cold):** compressed/summarized old episodes, rarely retrieved.

**Promotion/demotion:** importance + recency + access-frequency drive promotion to working memory and demotion to archival. Consolidation (a reflection job) summarizes clusters of episodic memories into semantic memory and archives the raw.

**Schema sketch** (`workspace` is RAM; archival adds a `summaries` table — see §27).

---

## 20. Goal System Design

**Why it should exist:** FRIDAY is "not a chatbot." Without persisted goals it cannot be project-aware or proactive — it only reacts. **Problem solved:** continuity of intent across sessions. **Alternatives:** encode goals as special memories (cheap, but no lifecycle/observability) — rejected for a first-class store. **Tradeoff:** a goal engine adds scheduling/priority complexity; mitigated by keeping goals *declarative data* acted on by the reflection loop, not autonomous threads.

**Model:** `Goal{ id, title, description, status(active|paused|done|abandoned), priority, parent_id, created_at, due_at, progress, success_criteria, owner(user|friday) }` plus `goal_events` for an audit trail. Goals link to memories and decisions. The Goal Engine: surfaces relevant goals during `recall`, proposes next actions during `reflect`, and never executes actions itself without the Skill layer + oversight policy.

**Integration:** `recall` injects active goals into context; Mission Control (§21) is its UI; the codex agent becomes "a goal-bearing agent" rather than a special case.

---

## 21. Mission Control Design

**Why:** human oversight needs a single pane. Today proposals live in an Obsidian vault and jobs live in `_jobs` — no unified view of *what FRIDAY is trying to do, what it did, and what needs approval*.

**Surface (HUD panel + API):**
- **Goals** (active/blocked/done, progress)
- **Approvals queue** (codex proposals, autonomous-action requests) with approve/reject/defer
- **Activity timeline** (decisions, tool calls, autonomous acts) from the Decision Log
- **Budgets** (autonomy time/action/spend remaining)
- **Health** (subsystems, model status, memory stats, index drift)

**API:** `GET /api/mission`, `POST /api/approvals/<id>`, `GET /api/goals`, `GET /api/health`. Integrates with the existing SSE stream. **Complexity:** Medium; mostly aggregation over new stores.

---

## 22. World Model Design

**Why:** "knowledge graph" needs explicit entities/relations; flat notes can't answer multi-hop queries ("which projects use Groq and are blocked?"). **Approach:** layer a graph over the vault, don't replace it. The vault stays the human-readable, Obsidian-graph-friendly projection; the graph store is the queryable index.

**Store options & tradeoff:**
- **SQLite entity/edge tables** (recommended start): zero new infra, transactional with memory, good to ~10⁶ edges. 
- **Embedded graph DB (e.g., Kùzu)**: better multi-hop, new dependency.
- **RDF/triple store:** standards-friendly, heavier, overkill now.

Start with SQLite `entities`/`relations` (§27), add a graph engine only when multi-hop query latency demands it. Entities carry `confidence` and `provenance` (links to source memories/notes) feeding the Truth Engine.

---

## 23. Reflection System Design

**Why:** self-improvement and memory consolidation require FRIDAY to *think about its own history* on a cadence, not per turn. **Problem solved:** unbounded raw memory, ungrounded mood drift, no learning loop beyond `record_feedback`. **Alternatives:** do consolidation inline per turn (latency + noise) — rejected.

**Jobs (scheduled via runtime, off the request path):**
- **Consolidation:** cluster recent episodic memories → summaries → semantic memory; archive raw.
- **Reflection:** "what worked / what didn't" over the Decision Log → new preferences, goal updates, codex proposals.
- **Truth maintenance:** re-evaluate low-confidence/conflicting facts (§24).
- **Mood reconciliation:** explain mood from evidence; write to Decision Log.

Each job is bounded (time/items), idempotent, and emits trace + Decision Log entries so reflection is *explainable*.

---

## 24. Truth Engine Design

**Why:** accumulating knowledge over years guarantees contradictions and staleness. Without conflict resolution, FRIDAY confidently recalls wrong things. **Problem solved:** trust and correctness of long-lived knowledge.

**Mechanics:**
- Every fact/entity carries `confidence`, `provenance[]`, `observed_at`, `supersedes`/`contradicts` links.
- On new fact: detect conflict (same subject+predicate, different object) → resolve by recency × source-trust × confidence; mark losers `superseded`, don't delete (auditability).
- Expose a **correction API** (`forget`/`amend`) — wiring the missing deletion path from §8.
- Surface unresolved conflicts to Mission Control for human adjudication.

**Tradeoff:** adds write-time cost and schema complexity; essential at the "years of knowledge" scale, optional at hundreds of facts — build the schema now, the resolver when fact volume warrants.

---

## 25. Skill System Design

**Why (the highest-leverage 4.0 addition):** "tool usage" and safe actuation need a uniform contract; otherwise every capability is bespoke and `friday_action` becomes an unbounded confused deputy. **Problem solved:** extensibility (dozens of tools) + permissioned safety + testability.

**Contract:**
```python
class Skill(Protocol):
    name: str
    description: str            # for the planner/LLM to choose it
    input_schema: dict          # JSON schema; validated before run
    permission: Permission      # AUTO | CONFIRM | FORBIDDEN_BY_DEFAULT
    def run(self, args: dict, ctx: SkillContext) -> SkillResult: ...
```
A **registry** discovers skills (manifest per skill), exposes their schemas to the planner, validates inputs, enforces permission policy (CONFIRM routes to Mission Control approvals), times out, and logs every invocation to the Decision Log. Existing `friday_action`, `friday_visual`, `friday_pdf`, `friday_whatsapp` become skills.

**Alternatives:** free-form function-calling against the LLM (less safe, no policy layer) — rejected for an actuating desktop agent. **Complexity:** Medium; the contract is small, the payoff compounds. **Maintenance:** *lowers* it — new capability = one self-contained skill + manifest + test.

---

## 26. Decision Memory Design

**Why:** explainability and oversight require a durable, queryable record of *why* FRIDAY did what it did — chosen route, models, skills, goals, confidence, cost, outcome. Today none of this is captured. **Problem solved:** observability, post-hoc reflection, debugging, trust.

**Record:** `decision{ id, trace_id, turn_id, ts, intent, route_to, models_used, skills_invoked, goals_touched, confidence, cost_tokens, latency_ms, outcome, rationale, was_autonomous }`. Written at the end of every cognitive cycle. Feeds Reflection (§23), Mission Control timeline (§21), and a future "explain your last answer" capability. This is also the dataset that makes the codex agent's self-improvement *grounded* in real behavior rather than static code inspection.

---

## 27. Database Schemas (proposed, additive + migration-gated)

Add a migration runner first:
```sql
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at REAL);
```

Memory (evolve existing; note `memories.embed_id` already exists — start using it):
```sql
ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE memories ADD COLUMN last_access  REAL;
ALTER TABLE memories ADD COLUMN tier         TEXT NOT NULL DEFAULT 'episodic'; -- working|episodic|semantic|archival
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, topic, content_rowid='id');

CREATE TABLE IF NOT EXISTS summaries (        -- consolidation output
  id INTEGER PRIMARY KEY, source_ids TEXT, summary TEXT, topic TEXT,
  importance REAL, created_at REAL, embed_id INTEGER);
```

World model / Truth:
```sql
CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY, name TEXT, type TEXT, confidence REAL DEFAULT 0.8,
  provenance TEXT, observed_at REAL, status TEXT DEFAULT 'active');
CREATE TABLE IF NOT EXISTS relations (
  id INTEGER PRIMARY KEY, subject_id INTEGER, predicate TEXT, object_id INTEGER,
  confidence REAL DEFAULT 0.8, provenance TEXT, observed_at REAL,
  supersedes INTEGER, status TEXT DEFAULT 'active');
CREATE INDEX IF NOT EXISTS idx_rel_subject ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_rel_object  ON relations(object_id);
```

Goals / Decisions:
```sql
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY, title TEXT, description TEXT, status TEXT DEFAULT 'active',
  priority INTEGER DEFAULT 3, parent_id INTEGER, success_criteria TEXT,
  progress REAL DEFAULT 0.0, owner TEXT DEFAULT 'user',
  created_at REAL, due_at REAL);
CREATE TABLE IF NOT EXISTS goal_events (
  id INTEGER PRIMARY KEY, goal_id INTEGER, kind TEXT, detail TEXT, ts REAL);

CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY, trace_id TEXT, turn_id INTEGER, ts REAL,
  intent TEXT, route_to TEXT, models_used TEXT, skills_invoked TEXT,
  goals_touched TEXT, confidence REAL, cost_tokens INTEGER, latency_ms INTEGER,
  outcome TEXT, rationale TEXT, was_autonomous INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_decisions_trace ON decisions(trace_id);
```

Keep SQLite as source of truth; vectors are a **derived, rebuildable** index keyed by `embed_id`.

---

## 28. Event Flow Diagrams

**Turn (4.0, fast path) — events actually dispatched by the runtime loop:**
```
perceive    USER_TEXT ───────────────► runtime.bus
recall      CONTEXT_READY ◄── Memory Service + World Model + Goal Engine
deliberate  THINKING_START ─► route ─► (Local|Neural|Codex|Planner) ─► Critic
            TRUTH_CHECKED  ◄── Truth Engine
act         SKILL_INVOKE ─► Registry ─► (permission?) ─► CONFIRM→approvals
respond     THINKING_DONE ─► Voice(SPEAK_*) + Face(UI_UPDATE)
reflect     DECISION_LOGGED ─► Decision Memory ; (async) CONSOLIDATE/REFLECT
```

**Background cognition (runtime scheduler):**
```
every N min ─► CONSOLIDATE ─► summaries + archival
nightly     ─► REFLECT ─► preferences/goals/codex-proposals
on conflict ─► TRUTH_MAINTAIN ─► supersede/flag ─► Mission Control
```

The crucial change vs. today: these arrows are **real** because exactly one event loop consumes the queue and `emit_threadsafe` posts to it correctly.

---

## 29. UML-style Architecture Diagrams

**Component (4.0):**
```
            ┌───────────────┐
            │    Runtime    │  (loop + threadpool + model mgr + scheduler)
            └──────┬────────┘
   ┌───────────────┼──────────────────────────┐
   ▼               ▼                           ▼
┌────────┐   ┌──────────────┐          ┌───────────────┐
│ Brain  │──▶│   Cognition  │          │ Observability │
│(facade)│   │  Context/    │          │ trace/metrics │
└───┬────┘   │  Reflect/    │          └───────────────┘
    │        │  Goals/Truth │
    │        └──────┬───────┘
    ▼               ▼
┌────────────┐ ┌──────────────┐  ┌───────────────┐
│   Skills   │ │   Memory     │  │  World Model  │
│  Registry  │ │   Service    │  │ entities/rel  │
└─────┬──────┘ └──────┬───────┘  └──────┬────────┘
      ▼               ▼                 ▼
   Tools/Action   Vector Substrate (shared, namespaced)
```

**Class (Memory Service):**
```
MemoryService
  + remember(turn) : id
  + recall(query, budget) : Context
  + consolidate() : void
  + forget(id) / amend(id) : void
  - store: SqliteStore         (source of truth)
  - index: VectorIndex         (HNSW, rebuildable, keyed by embed_id)
  - tiers: TierPolicy
```

---

## 30. Recommended Folder Structure (4.0)

```
core/
  runtime/        # bus(real), loop, threadpool, model_manager, scheduler, health
  cognition/      # context_assembler, reflection, goals, truth, planner, critic
  memory/         # service, sqlite_store, vector_index, tiers, migrations/
  knowledge/      # world_model, vault_store, entities, vector_substrate
  skills/         # registry, base, permissions, builtin/ (action, visual, pdf, ...)
  perception/     # frame_source, analyzers/, emitter   (vision, new)
  persona/        # psyche, empath
  brain/          # brain(facade), neural, local            (slimmed)
  io/             # face(+mission control), notify, gesture
  voice/          # unchanged, behind threadpool boundary
  observability/  # tracing, metrics, decision_log
infra/  → folds into runtime/
```

`brain/` shrinks to a facade; the heavy logic moves to `cognition/` and `memory/`. Keep the side-effect-free import rule across all of it.

---

## 31. New Modules to Add (priority-ordered)

1. **`runtime/`** — *foundational*, unblocks everything. Complexity M.
2. **`observability/` (tracing + decision_log)** — cheap, huge explainability ROI. Complexity S–M.
3. **`memory/` service** (re-platform chronicle) — scalability keystone. Complexity M–L.
4. **`skills/` registry** — extensibility + safe actuation. Complexity M.
5. **`cognition/context_assembler`** — quality jump per turn. Complexity S–M.
6. **`cognition/goals` + Mission Control** — agency + oversight. Complexity M.
7. **`cognition/reflection`** — learning loop + consolidation. Complexity M.
8. **`knowledge/world_model` (entities/relations) + `truth`** — long-horizon correctness. Complexity M–L.
9. **`perception/`** — true vision. Complexity L.

---

## 32. Existing Modules to Refactor

- **`friday_signal` → `runtime/bus`**: one running loop; correct `emit_threadsafe`; route real pipeline events. *(fixes W1)*
- **`friday_spine` → `runtime` bootstrapper**: keep the great degraded-boot pattern; delegate concurrency to the runtime. *(fixes W2)*
- **`friday_chronicle` → `memory/`**: per-thread conns, FTS5, ANN index keyed by `embed_id`, migrations, forgetting/consolidation, integrity check. *(fixes W3, W6-partial, W9)*
- **`friday_world`**: split storage (vault) from index (shared substrate); add provenance/confidence. *(fixes W10)*
- **`friday_face`**: job TTL/eviction, session token auth, Mission Control endpoints. *(fixes W11, security)*
- **`friday_action` → a Skill**: behind permission policy. *(security)*
- **`friday_neural`**: pull model loads into the model manager; embed-once context. *(fixes W6)*

---

## 33. Features to Remove or Simplify

- **Remove the phantom bus *or* make it real** — do not ship a third state. (Strong recommendation: make it real.)
- **Collapse dual config lookup** — one config resolver; `.env` for secrets, one `friday_config.json` location, delete the empty-template shadow that `_pick_config_path` exists to dodge.
- **Simplify ad-hoc `threading.Thread` spawns** — route through the runtime threadpool.
- **Fold `infra/` into `runtime/`** — fewer seams.
- **Defer `friday_phone`/`friday_whatsapp`** to skills (don't invest until the Skill layer exists).
- **Fix, don't expand, `friday_mic_test`** (add `__main__` guard) and route voice temp files to a temp dir.

---

## 34. Highest-ROI Improvements (effort × impact)

| Rank | Improvement | Effort | Impact | Why |
|---|---|---|---|---|
| 1 | Decision Log + per-turn tracing | S | ⭐⭐⭐⭐⭐ | Instant explainability/observability; data for everything later |
| 2 | Make the bus real / pick concurrency | M | ⭐⭐⭐⭐⭐ | Removes a correctness trap; unblocks reactive features |
| 3 | Memory: FTS5 + ANN + integrity + `embed_id` | M | ⭐⭐⭐⭐⭐ | Scalability wall removed; recall quality up |
| 4 | Context Assembler (token budget + rerank) | S–M | ⭐⭐⭐⭐ | Better answers every single turn |
| 5 | Skill registry (+ migrate action) | M | ⭐⭐⭐⭐ | Extensibility + safety |
| 6 | Migrations + schema_version | S | ⭐⭐⭐⭐ | Protects years of user data |
| 7 | Model manager (preload/unload) | S–M | ⭐⭐⭐ | First-turn latency, multi-model future |
| 8 | Test suite + CI on the core | M | ⭐⭐⭐⭐ | Net for self-modifying system |

---

## 35. Implementation Roadmap

**Phase 0 — Stabilize (1–2 wks):** migrations + `schema_version`; chronicle concurrency fix (per-thread conns, use `_conn_lock` or drop it for pooling); FAISS↔SQLite integrity check on boot; voice temp-file + mic_test hygiene; rotate keys. *No new features — pay down the dangerous debt.*

**Phase 1 — Foundations (3–5 wks):** Runtime (real bus + threadpool + model manager); Observability (tracing + Decision Log); test suite + CI. *Now the system is reliable and inspectable.*

**Phase 2 — Memory & Context (3–4 wks):** Memory Service (tiers, FTS5, ANN, consolidation, forget/amend); Context Assembler. *Recall scales and improves.*

**Phase 3 — Agency (4–6 wks):** Skill Registry (+migrate action/visual/pdf); Goal Engine; Mission Control. *FRIDAY becomes goal-bearing and overseeable.*

**Phase 4 — Cognition depth (4–6 wks):** Reflection jobs; World Model (entities/relations) + Truth Engine. *Long-horizon learning and correctness.*

**Phase 5 — Perception (open-ended):** `perception/` pipeline; multi-model orchestration → 5.0 cognitive loop.

---

## 36. Development Priorities (principles)

1. **Reliability before capability** — never stack a feature on an unrun event loop.
2. **Source of truth is SQLite/vault; vectors are derived** — always rebuildable.
3. **Everything FRIDAY does is logged as a decision** — no unexplained actions.
4. **Actuation is permissioned** — skills, not free functions.
5. **Schema changes go through migrations** — user data outlives code.
6. **Preserve the invariants** — side-effect-free imports, degraded boot, human-gated self-edits.
7. **Bound every background job** — time, items, idempotency.

---

## 37. Risks & Failure Points

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Silent memory corruption (FAISS/SQLite desync) | High (current) | High | `embed_id` in-row, integrity check, rebuildable index |
| Building features on the dead bus | High | High | Fix W1 in Phase 1 before any reactive feature |
| Confused-deputy actuation via local HTTP | Medium | High | Session token + skill permissions |
| Self-improving agent edits without tests | Medium | High | Test-gated apply; require diff+test in proposals |
| Unbounded memory growth degrades recall/latency | High (long-term) | Medium | Consolidation + forgetting + ANN |
| Single-process model RAM pressure | Medium | Medium | Model manager load/unload; process isolation if needed |
| Schema evolution breaks user DBs | Medium | High | Migration runner from Phase 0 |
| Scope explosion (5.0 before 4.0 solid) | High | High | Enforce the phase gates; foundations first |

---

## 38. Sample Code Skeletons

### 38.1 Runtime (bus made real + thread-pool boundary)
```python
# core/runtime/runtime.py
import asyncio, threading
from concurrent.futures import ThreadPoolExecutor
from core.infra.friday_signal import EventBus, Signal  # reuse the existing bus class

class Runtime:
    """One event loop in a dedicated thread; a thread-pool for blocking work."""
    def __init__(self, workers: int = 4):
        self.bus = EventBus()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="friday-io")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True, name="friday-runtime")

    def start(self):
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self.bus.start())   # the loop that 3.0 never started
        self._loop.run_forever()

    def emit_threadsafe(self, signal: Signal, data=None, source="thread", priority=5):
        # CORRECT cross-thread emit — fixes W1's emit_sync fragility.
        asyncio.run_coroutine_threadsafe(
            self.bus.emit(signal, data, source, priority), self._loop)

    async def offload(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn, *args)
```

### 38.2 Decision Log (observability keystone)
```python
# core/observability/decision_log.py
import time, json, uuid, sqlite3

def log_decision(db: sqlite3.Connection, *, trace_id, turn_id, intent, route_to,
                 models_used, skills_invoked, goals_touched, confidence,
                 cost_tokens, latency_ms, outcome, rationale, was_autonomous=False):
    db.execute("""INSERT INTO decisions
        (trace_id,turn_id,ts,intent,route_to,models_used,skills_invoked,
         goals_touched,confidence,cost_tokens,latency_ms,outcome,rationale,was_autonomous)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (trace_id, turn_id, time.time(), intent, json.dumps(route_to),
         json.dumps(models_used), json.dumps(skills_invoked), json.dumps(goals_touched),
         confidence, cost_tokens, latency_ms, outcome, rationale, int(was_autonomous)))
    db.commit()

def new_trace() -> str:
    return uuid.uuid4().hex[:12]
```

### 38.3 Skill contract + registry
```python
# core/skills/base.py
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

class Permission(Enum):
    AUTO = auto(); CONFIRM = auto(); FORBIDDEN_DEFAULT = auto()

@dataclass
class SkillResult:
    ok: bool; output: str = ""; data: dict | None = None

class Skill(Protocol):
    name: str; description: str; input_schema: dict; permission: Permission
    def run(self, args: dict, ctx) -> SkillResult: ...

# core/skills/registry.py
class SkillRegistry:
    def __init__(self, approvals, decisions):
        self._skills: dict[str, Skill] = {}
        self._approvals = approvals      # Mission Control queue
        self._decisions = decisions

    def register(self, skill: Skill): self._skills[skill.name] = skill
    def manifest(self) -> list[dict]:   # fed to the planner/LLM
        return [{"name": s.name, "description": s.description,
                 "input_schema": s.input_schema} for s in self._skills.values()]

    def invoke(self, name: str, args: dict, ctx) -> SkillResult:
        skill = self._skills[name]
        self._validate(skill.input_schema, args)            # jsonschema
        if skill.permission is Permission.CONFIRM and not self._approvals.granted(name, args):
            return SkillResult(ok=False, output="awaiting approval")
        result = skill.run(args, ctx)
        # every invocation is a decision (explainability)
        return result
```

### 38.4 Memory Service (rebuildable index keyed by embed_id)
```python
# core/memory/service.py
class MemoryService:
    def __init__(self, store, index, tiers):
        self._store, self._index, self._tiers = store, index, tiers

    def remember(self, role, content, topic="", importance=0.5, mem_type="conversation") -> int:
        mem_id = self._store.insert(role, content, topic, importance, mem_type)
        vec = self._index.embed(content)                 # embed once
        embed_id = self._index.add(vec)                  # ANN add_with_ids
        self._store.set_embed_id(mem_id, embed_id)       # atomic in-row link (fixes W3)
        return mem_id

    def recall(self, query, budget_tokens=1200):
        qvec = self._index.embed(query)
        hits = self._index.search(qvec, k=12)            # HNSW
        rows = self._store.by_embed_ids(hits)
        return self._tiers.assemble(query, rows, budget_tokens)  # rerank + token budget

    def rebuild_index(self):                             # integrity recovery
        self._index.reset()
        for mem_id, content in self._store.iter_all():
            self._store.set_embed_id(mem_id, self._index.add(self._index.embed(content)))
```

### 38.5 Goal Engine (declarative, acted on by reflection)
```python
# core/cognition/goals.py
def relevant_goals(db, query_topic: str, limit=3) -> list[dict]:
    rows = db.execute("""SELECT * FROM goals WHERE status='active'
                         ORDER BY priority ASC, (due_at IS NULL), due_at ASC
                         LIMIT ?""", (limit,)).fetchall()
    return [dict(r) for r in rows]

def propose_next_actions(db, goal: dict, planner) -> list[str]:
    # Called by the reflection loop, NOT inline — keeps the turn fast.
    return planner.steps_for(goal["title"], goal.get("success_criteria", ""))
```

---

### Closing note
FRIDAY 3.0 has the *bones* of a real cognitive OS and several decisions a lot of teams get wrong (local-first, side-effect-free imports, human-gated self-edits, degraded boot). The work ahead is not a rewrite — it's **making the foundation honest** (run the loop, make memory durable, log every decision) and then layering the four agency pillars (skills, goals, reflection, perception) on top. Do Phase 0 and Phase 1 before anything else; they are the difference between a system that survives five years and one that quietly corrupts itself in year one.

*I've kept every recommendation tied to either verified source or a clearly-labeled inference. Where I marked [inferred], let's confirm against the real modules (`friday_psyche`, `friday_empath`, `friday_sovereign`, `friday_codex_agent`, `friday_action`) before committing roadmap dates.*
