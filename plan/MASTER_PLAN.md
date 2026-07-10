# FRIDAY 3.0 — Master Plan (Canonical)

**Status:** The single canonical plan. Supersedes `docs/FRIDAY_5X_ROADMAP.md`
and the 2026-07-10 morning revision of this file.
**Owner:** Satvik. **Platform today:** Windows, CPU-only.
**Created:** 2026-07-10 (revised same day: Friday 3.0 era).

> **Era naming (Satvik, 2026-07-10):** everything shipped to date — m21–m31,
> perception, brains, executive, launcher, conversation quality — is the
> **Friday 2.0 era**. **Friday 3.0** is this plan: a perfected core, a stable
> layer that wraps around it, and resident autonomy. (Historical docs that say
> "3.0 spine" or "5.x" refer to old internal numbering; this file's naming wins.)

> **Prime rule (unchanged):** cognition is internal and local. External LLMs
> are temporary teachers or fallback language tools, never the permanent
> brain. The M30 Groq teacher is a temporary exception, retired in Track A.

---

## 1. Where we stand (absorbed progress log)

m21–m31 complete and tagged: cutover to one boot path (m21), one memory
(m22), internal mind (m23, m28), truthful autonomy + tests (m24), live
context (m25), security + adversarial hardening (m26, m29), selective
learning (m27), Groq teacher (m30), human-level listening (m31).

Open gaps carried into Track A: ~35 FridayAction methods bypass the
Executive/security/audit pipeline; World Model not yet perception-fed;
independence not yet measured over real use; local reasoning still
flan-t5-class; Groq teacher still on the path.

---

## 2. What Friday 3.0 is

Three dependency-ordered tracks, plus one explicitly parked horizon:

| Track | Theme | Milestones |
|---|---|---|
| **A — Perfect the core** | Upgrade the 2.0 base from the ground up (no deletions), then: nothing bypasses the Executive; reasoning becomes genuinely local | M32–M36 |
| **B — The wrapper** | One stable boundary around the whole system: the Friday Core API | M37 |
| **C — Resident autonomy** | She runs 24/7 as a governed, self-improving resident | M38 |
| *Horizon (parked)* | *Platform layer: CPU+GPU, Windows+macOS* | *unscheduled* |

A track does not start until the previous track's exit criteria pass. Every
milestone lands with tests + a commit + tag (continuing `m21…m31`).

---

## 3. Track A — Perfect the core

### M32 — Base Perfection  (`m32-base-perfection`)

**Directive (Satvik, 2026-07-10):** before any wrapper, upgrade the 2.0 base
from the ground up. **No code is deleted** — every module is repaired and
strengthened in place. Source of truth for defects: `FRIDAY_VERIFIED_STATE.md`
(line-verified 2026-07-10 — the legacy-path defects it lists are still live).

Upgrade ledger, in dependency order (each stage: fix + tests + commit):

1. **`core/infra/`** — Event bus lifecycle: one owned asyncio loop on a
   dedicated thread + `run_coroutine_threadsafe` bridge so `emit_sync` is
   real, not /dev/null. Preserve the Signal taxonomy + handler isolation.
2. **`core/knowledge/`** — Chronicle: actually acquire `_conn_lock`
   (single shared SQLite connection is used from ≥3 threads today); write the
   existing-but-unused `memories.embed_id` column; persist the FAISS index on
   a schedule instead of every-20-inserts. Sovereign: fix the dead
   `extract_and_store` call (`friday_neural.py:489` — missing `intent`,
   TypeError swallowed since 3.0) without double-extracting; wire `used_api`
   truthfully from whether `friday_local` answered (`friday_brain.py:291`
   hardcodes `True`); increment `concepts_learned`.
3. **`core/persona/`** — Psyche: feed Empath's computed tone into mood
   (today a default `"neutral"` is passed instead); add the negative path to
   `record_turn` (trust currently only ever rises).
4. **`core/brain/`** — Neural: repair the pipeline call sites above; make the
   local-vs-cloud answer source an explicit signal consumed by Sovereign and
   DecisionLog.
5. **`core/io/`** — FridayAction: add the missing `threading` import
   (`start_battery_alert` raises NameError today). Face/HUD: replace the
   hardcoded `SECRET_KEY` (`friday_face.py:368`) with a generated local
   token, add `_jobs` eviction (unbounded today), and either make the
   mini-brain roster real or relabel it honestly.
6. **Re-point the HUD** (`friday_face.py:244`, `friday_app.py`,
   `friday_proactive.py:135`, `friday_pdf.py`) off the legacy brain onto the
   same cognition path voice uses — the last consumers of the old pipeline.

**Exit:** every VERIFIED defect in `FRIDAY_VERIFIED_STATE.md` is fixed or
formally waived in that doc; no module outside `legacy/` imports
`friday_brain`/`friday_neural`; pytest green.

### M33 — Mini-Brain Fast Path  (`m33-mini-brains`) ✅ *(inserted at Satvik's request, 2026-07-10)*

Deterministic specialist mini brains in front of the model team
(`core/intelligence/mini_brains.py` + wiring in `IntelligenceOS.think`):
math, clock, units, system status, memory recall — each claims only the task
shapes it can answer EXACTLY, answers in milliseconds, and refuses everything
else (a wrong fast answer is worse than a slow correct one; intent gating is
tested, e.g. "call 555-2368" never gets an arithmetic answer). Per-brain
latency budgets (500 ms) are measured with violations counted in
`status()["mini_brains"]`, never hidden. Honesty note: open-ended reasoning on
a CPU box cannot promise <500 ms — the fast path is how *common* tasks meet
the budget; the model team's latency is tracked against it in M36 instead.
New specialists are added here as task shapes recur.

**Exit (met):** fast-path answers measured < 500 ms; misses fall through with
zero behaviour change; cortex stats exposed. Tests: `test_mini_brains.py` (29).

### M34 — Executive Supremacy & Skills  (`m34-executive-supremacy`)

Infrastructure already exists (`core/skills/`: registry, executor, manifests,
permissions, audit; `core/security/`: roles, policies, approvals, sandbox,
validation, security_log) but only 4 builtin skills are registered while
`core/io/friday_action.py` holds ~35 ungoverned methods.

1. Wrap FridayAction methods as registered Skills by risk tier — thin
   wrappers **delegating** to FridayAction (refactor, don't rewrite):
   - **Tier 1, read-only, auto-approved:** `screenshot`, `get_clipboard`,
     `get_brightness`, `get_system_summary`, `get_wifi_status`,
     `check_internet`, `get_ip`, `search_files`, `get_recent_files`,
     `capabilities`.
   - **Tier 2, reversible, policy-approved:** `open_app`, `focus_window`,
     `minimize_window`, `maximize_window`, `set_volume`, `mute`, `unmute`,
     `media_play_pause`, `media_next`, `media_prev`, `brightness_up`,
     `brightness_down`, `set_brightness`, `open_url`, `copy_to_clipboard`,
     `move_mouse`, `scroll`.
   - **Tier 3, human-approval-gated:** `close_app`, `type_text`, `press_key`,
     `click`, `run_shell`, `add_to_startup`, `remove_from_startup`,
     `sleep_pc`, `restart_pc`.
2. Executive routes all actions via the skill router; direct
   `FridayAction.execute(...)` call sites removed from the cognition path.
3. Simulation Brain consulted for Tier 3 and low-confidence Tier 2 (advisory
   hook exists — wire it).
4. m29 voice-safety carries over: spoken Tier 3 commands always two-step
   confirm.
5. Tests: per-tier registration/policy/audit tests + one end-to-end
   spoken-command → Executive → skill → `audit.db` → DecisionLog test.

**Exit:** every side-effecting action in `audit.db` with a DecisionLog trace;
zero ungoverned action invocations on the boot path; pytest green.

### M35 — Live World & Truthful Independence  (`m35-live-world`)

1. World Model continuously fed by the Perception Hub (observations already
   emitted — connect the pipe). Proof: "what's happening right now?" answered
   from the model, no LLM call.
2. Independence measured truthfully from DecisionLog (`was_autonomous`,
   `models_used`) over a week of normal use; recorded in `docs/BENCHMARKS.md`.

**Exit:** both proofs demonstrated and logged.

### M36 — Local Intelligence  (`m36-local-intelligence`)

1. Tiered local reasoning stack: small quantized instruct model
   (llama.cpp/Ollama, CPU today) as main local reasoner; flan-t5 + rule-based
   team beneath; deeper collaborative passes on low confidence.
2. Retire the Groq teacher once local matches its critic-scored quality.
3. Lazy-load every model behind the ModelRegistry; profile boot + RAM.

**Exit (per the Phase-B benchmark script):** cold boot < 10 s · simple voice
reply < 700 ms · ≥ 50% of turns fully local at equal critic-scored quality ·
Groq off the production path.

---

## 4. Track B — The wrapper (M37, `m37-core-api`)

The "layer that wraps around Friday 2.0": a single stable boundary — the
**Friday Core API** — through which *every* consumer talks to her. Nothing
reaches inside the core anymore.

1. Define the boundary surface (versioned, small): `converse`, `perceive`
   (push observations), `act` (skill invocation, governance included),
   `query` (world/user/self models, memory), `learn`, `status`, `events`
   (subscribe to thoughts/situations/decisions).
2. Re-point existing consumers through it: HUD (`friday_face`), voice loop,
   `/run-friday` headless driver, CLI. Delete side-door imports.
3. The API is transport-agnostic: in-process today; the same surface later
   serves remote/mobile/second-machine clients without core changes.
4. Contract tests on the boundary — the API becomes the compatibility
   guarantee for everything built after.

**Exit:** all shipped UIs/drivers run exclusively through the Core API;
boundary contract tests green; an external consumer (e.g. a 20-line script)
can drive a full conversation turn through it.

**Why this matters for the horizon:** the parked platform work (GPU, macOS)
happens *under* this boundary — consumers never notice. The wrapper is what
makes "runs anywhere" a swap instead of a rewrite.

---

## 5. Track C — Resident autonomy (M38, `m38-resident`)

1. FRIDAY runs 24/7 as a resident process: starts with Windows, survives
   sleep/wake, degrades gracefully (mic/camera loss ≠ crash).
2. Autonomous goals (m28) execute end-to-end while resident: propose →
   human-gate → plan → act through skills → observe → reflect → learn.
3. Self-improvement loop closes: codex proposals + reflection lessons
   measurably change behavior; independence % trends up in `BENCHMARKS.md`.
4. Resource governor: RAM/CPU budgets enforced so residency never degrades
   the machine (budgets tracked by the benchmark).

**Exit:** one week of continuous residency with zero manual restarts; ≥ 1
self-generated goal completed end-to-end during it; resource budgets held.

---

## 6. Horizon — platform layer (parked at Satvik's request, 2026-07-10)

Not scheduled; enters the plan only as a track with exit criteria when
Tracks A–C are done. Recorded so the intent isn't lost:

- **Compute:** CPU + GPU backends behind the ModelRegistry (llama.cpp CUDA /
  DirectML / Metal later); models declare requirements, registry picks.
- **OS:** Windows + macOS via the platform adapter (seed exists:
  `core/launcher/platform_adapter.py`). Windows-only code (pycaw, WebView2,
  startup registry) isolated behind it during Tracks A–B as a side effect of
  the skill wrappers and Core API — so the port is contained, not a rewrite.

---

## 7. Rules (carried forward, unchanged)

1. Cognition is internal; LLMs are temporary tools.
2. Runtime owns every singleton; no duplicate model loading.
3. All subsystems communicate through the Runtime / Event Bus.
4. The Executive is the only decision-maker; nothing bypasses it.
5. Learning never blocks responses; memory retrieval precedes reasoning.
6. Simulation is used for uncertain or high-impact decisions.
7. Every milestone lands with tests, observability, commit + tag.
8. Performance is measured continuously, never optimized blind.
9. Spoken input is an attack surface (m29); new skills inherit that posture.
10. **New:** nothing consumes the core except through the Core API once M37
    lands; new Windows-only code goes behind the platform adapter.
11. **New (Satvik, 2026-07-10):** the base is upgraded, never deleted —
    repairs happen in place; `legacy/` quarantine is the only exception.

## 8. Risk register

| Risk | Mitigation |
|---|---|
| Plan churn — a new plan every session | This file is the only plan; changes amend it, never fork it |
| Wrapper built over a leaking core | Track A gates Track B; exit criteria enforced |
| Skill wrappers drift from FridayAction | Wrappers delegate; FridayAction stays the single implementation |
| `run_shell` as a governed skill | Tier 3 + sandbox + two-step voice confirm + audit + allowlist |
| Core API becomes a god-interface | Surface kept small and versioned; contract tests block breakage |
| RAM exhaustion (resident + local models, CPU box) | Lazy-load via ModelRegistry; resource governor in M36; benchmark-tracked |
| Groq teacher permanent by inertia | M34 exit criterion removes it |
| Platform work sneaks in early | Horizon is parked; only isolation-behind-adapters allowed in A–B |
