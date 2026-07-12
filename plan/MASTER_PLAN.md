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
> brain. The M30 Groq teacher is the ONLY big-model tier (Satvik, 2026-07-10:
> no new local reasoning models — she learns from Groq for now); it is
> retired when the learn-back flywheel makes it unnecessary — Satvik's call,
> consult rate tracked in M36.

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
| **A — Perfect the core** | Upgrade the 2.0 base from the ground up (no deletions), then: nothing bypasses the Executive; reasoning becomes genuinely local | M32–M35 ✅ + 2 open |
| **B — The wrapper** | One stable boundary around the whole system: the Friday Core API | open |
| **C — Resident autonomy** | She runs 24/7 as a governed, self-improving resident | open |

> **Numbering rule (2026-07-10):** future milestones are numbered only when
> they land — planned-but-unbuilt work is named, not numbered. This file was
> renumbered three times in one day; never again.
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

### M34 — Executive Supremacy & Skills  (`m34-executive-supremacy`) ✅

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

**Landed (2026-07-10):** 37 skills in `core/skills/builtin/system_actions.py`
(11 SAFE/LOW read-only · 17 SAFE/MEDIUM reversible · 4 USER_APPROVAL/HIGH ·
5 ADMIN_ONLY/HIGH-CRITICAL), thin delegating wrappers over FridayAction,
registered via `register_builtins`. `shell.run` stays hard-DENIED by the
default policy — enabling it is an explicit owner act. Simulation advisory
wired: `Orchestrator(deliberator=…)` consults the Executive Brain's
`deliberate()` before HIGH/CRITICAL skills; `ask_user` stops autonomous
execution before the approval gate; advisory failure never blocks. Honest
note on item 4: no live voice→skill routing exists yet, so the two-step
confirm applies when that path lands — until then the ApprovalManager blocks
every Tier-3 invocation by construction (no auto-decider is wired). Tests:
`test_system_action_skills.py` (15).

### M35 — Device Wizard  (`m35-device-wizard`) ✅ *(pulled from the platform horizon at Satvik's request, 2026-07-10)*

For every user's machine — Mac, gaming PC, office laptop — the first-run
wizard decides her CPU/GPU split honestly:

- `core/launcher/device_plan.py`: detect backends (CUDA / Apple-Metal MPS /
  OpenVINO-GPU) → **measure** a ~10 s MiniLM-shaped micro-benchmark on CPU vs
  each measurable GPU → classify: `good_gpu` (≥2.0× measured) = local models
  + perception on GPU · `average_gpu` (≥1.2×) = perception only · `cpu_only`.
  Unmeasured backends (OpenVINO today) are recorded but NEVER selected —
  unproven is unused. Plan written to `friday_config.json:device_plan`.
- `core/intelligence/device.py`: the ONLY reader — `preferred_device()`
  always returns a safe torch device; anything unknown degrades to cpu.
  Consumers wired: flan-t5 pipeline + chronicle embedder.
- Wizard: `gpu` check + `plan_devices()` step in `first_run.py`;
  `python -m core.launcher.device_plan --write` is the diagnostics re-run.
- Honest note: Satvik's own box (Iris Xe, torch-cpu) measures `cpu_only` —
  correct behaviour. OpenVINO measurement is future horizon work.

**Exit (met):** wizard writes a measured plan; readers degrade safely; 16 new
tests (`test_device_plan.py`) + first-run/launcher regressions green.

### M36 — Brain Perfection  (`m36-brain-perfection`) ✅

A ground-up correctness pass over the thinking path (Intelligence OS +
conversation bridge + learning flywheel). Nine defects repaired, no module
rewritten:

1. **Stale-cache flywheel break (the big one):** the execution cache keyed on
   context key-*names* only — after Groq taught her something, the same
   question was served the pre-learning cached "I don't know" forever. The
   FULL context is now part of the key; new evidence is always recomputed.
2. **Blind deep pass:** the "think harder" escalation received an EMPTY
   context (no memories/knowledge). It now reasons over the same retrieved
   context as the first pass (`RouterResponse.context_used`).
3. **One retrieval per turn:** the bridge's duplicate provenance recall is
   gone — memory ids ride in `context_used` (with `private` flags).
4. **Router word boundaries:** "say"≠essay, "plan"≠airplane, "+" needs digits.
5. **RecallBrain → One Memory:** "do you remember…" now sees taught knowledge
   (DI via the cortex; chronicle stays as fallback; relevance floor 0.35).
6. **Teacher context, privacy-filtered:** Groq consults get the conversation
   window + non-private facts only (unknown provenance = private); taught
   answers store the question as `topic`.
7. **Conversation window:** last 6 turns ride in context; follow-up prompts
   ("what about in miles?") anchor retrieval to the previous user turn.
8. **Spoken-language mini brains:** "12 times 7", "15 percent of 80",
   "how many miles is 5 km", "what date is it" — STT reality, not symbols.
9. **Learning noise stopped:** per-turn formulaic reflection "lessons" no
   longer pollute the knowledge vault (only concrete mistakes persist);
   recomputable mini-brain answers are never stored as memories.

**Exit (met):** full suite green + 20 new regression tests across
`test_trace_execution / conversation_quality / intelligence_router /
mini_brains / teacher / learning_gate / context_builder / intelligence_os`;
end-to-end smoke over the real `IntelligenceOS.think()` (6 checks) green.

### M37 — Brain Tranche 2  (`m37-brain-tranche-2`) ✅

- **flan-t5 reads evidence:** the optional plugin outranked the builtin
  reasoner for GENERAL tasks on real boots yet ignored `request.context`
  and stamped a flat 0.7 — a base-model hallucination could clear the
  escalation threshold, blocking both taught memories and the teacher. Now:
  retrieved evidence is stitched into an extractive-QA prompt, confidence is
  honest (0.75 grounded / 0.4 free generation), and the ~1 GB pipeline warms
  on a background thread instead of hanging the first user turn.
- **Memory dedup:** `remember()` reinforces an existing (≥0.97 cosine) row —
  touch + max importance — instead of piling near-identical taught answers
  into the index; `amend()` can no longer supersede a memory with itself.
- **DateMathBrain:** "what day is it in 10 days", "how many days until
  December 25", "what day of the week is March 3 2027" — exact-or-silent.

**Exit (met):** full suite green + 13 new tests.

### M38 — Voice Layer Repair  (`m38-voice-repair`) ✅ *(the "weakest part" pass, Satvik 2026-07-11)*

`core/voice/` was the weakest production-path code: zero tests, three import
landmines, and a bug that killed the voice under an installed (Program Files)
deployment. Repaired in place:

- `friday_audio`/`friday_tts`/`friday_voice`: audio temp files live under the
  SYSTEM temp dir (per-process), never the CWD — a read-only install dir no
  longer silences her.
- `friday_voice.say()`: persistent pygame mixer (no per-sentence init/quit
  churn; barge-in's `music.stop()` always finds a live mixer), lazy imports,
  and an OFFLINE fallback — edge-tts needs network, so on failure Windows
  SAPI (built into the OS) speaks instead; every path guarded, never raises
  on the speech worker.
- `friday_mic_test`: no longer loads whisper AND records 5 s of audio AT
  IMPORT (the documented 3.0 gotcha) — everything behind `main()`.
- `friday_voice_loop`: the file had been accidentally overwritten with a copy
  of `setup.py` — importing it ran pip installs and a blocking `input()`.
  Restored to its documented role: the minimal senses → IOS → voice dev loop.

**Exit (met):** new `tests/test_voice_output.py` (10) + conversation/teacher
regressions green; full suite green.

### M39 — Trading AI Perfection  (`m39-trading-ai-perfection`) ✅

The vendored Athena trading assistant (`trading_ai/`, first committed
`c5c2b0f`) got the same audit-and-repair treatment. The 2026-07-11 rebuilt
core (signal engine, backtester, recommendation engine, outcome tracker,
market API, voice/screen alerts) audited CLEAN — conservative, honest,
tested (48 green). The June-21 leftovers carried real hazards, fixed in
place:

- `setupfile.py`: a one-shot rebuilder that DELETES project sources and
  rewrites them from stale June-21 copies embedded in the file — running it
  would silently regress every module edited since. Now refuses to run
  without `TRADING_AI_REBUILD_CONFIRM=yes`.
- `athena_dashboard.py`: Flask ran on `0.0.0.0` with `debug=True` — the
  Werkzeug debug console (arbitrary code execution) and portfolio data
  exposed to the whole LAN. Now 127.0.0.1, debug off.
- `athena.py`: logged in to the broker, spoke, and entered an infinite mic
  loop AT IMPORT. Everything behind `main()` now.
- `voice.py`: initialized the SAPI COM engine at import → lazy.
- `whatsapp_sender.py`: clear error when `DAD_PHONE` is unconfigured
  (was a cryptic pywhatkit crash); dotenv/pywhatkit imports lazy.

**Exit (met):** trading_ai suite 48 green + import-safety check; FRIDAY
suite untouched by construction (root `testpaths=tests`).

### Live World & Truthful Independence  *(open — numbered when it lands)*

1. World Model continuously fed by the Perception Hub (observations already
   emitted — connect the pipe). Proof: "what's happening right now?" answered
   from the model, no LLM call.
2. Independence measured truthfully from DecisionLog (`was_autonomous`,
   `models_used`) over a week of normal use; recorded in `docs/BENCHMARKS.md`.

**Exit:** both proofs demonstrated and logged.

### Local Intelligence  *(open — numbered when it lands)*

**Scope correction (Satvik, 2026-07-10): no new local reasoning models.**
The only big-model tier is the Groq teacher (M30) — FRIDAY learns from Groq
for now; a local instruct model (llama.cpp/Ollama) is NOT added. Local
quality rises through the learning flywheel instead:

1. The Groq learn-back loop is the quality engine: every teacher consult is
   gated (M27 selective learning), stored, and retrained into `local_qa` on
   schedule — the next similar question is answered locally without Groq.
2. Grow the mini-brain cortex (M33) and the rule-based team as recurring
   task shapes appear; deeper collaborative passes on low confidence stay
   local.
3. Lazy-load every model behind the ModelRegistry; profile boot + RAM.

**Exit (per the Phase-B benchmark script):** cold boot < 10 s · simple voice
reply < 700 ms · ≥ 50% of turns fully local at equal critic-scored quality ·
Groq consult rate measurably declining week over week. (Retiring the teacher
entirely stays the prime-rule end state; the date is Satvik's call.)

---

## 4. Track B — The wrapper: the Friday Core API *(open)*

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

## 5. Track C — Resident autonomy *(open)*

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

- **Compute (spec'd by Satvik, 2026-07-10):** CPU + GPU load splitting for
  every user's machine, decided by the **first-run wizard** (RC1
  `core/launcher/first_run.py` is the hook point):
  1. *Detect* available backends: Metal (Apple Silicon), CUDA (NVIDIA),
     Vulkan/OpenVINO (Intel/AMD iGPU), else CPU.
  2. *Measure, don't guess:* a ~10-second micro-benchmark (embedding batch +
     short generation) on CPU vs each GPU backend — spec sheets lie; an iGPU
     that benchmarks slower than CPU is classified "no useful GPU".
  3. *Classify into a tier and write a `device_plan` to `friday_config.json`:*
     · **good GPU** → her existing local models (flan-t5, embeddings,
       whisper STT) plus perception on GPU — there is no local big reasoner
       to layer-offload (see M36 scope correction); if one is ever approved,
       llama.cpp layer-offload slots in here;
     · **average GPU** → perception offload only, reasoning stays on CPU;
     · **none** → pure CPU (today's behaviour).
  4. The **ModelRegistry is the only reader** of the device plan — it places
     models; cognition code never references devices. Re-run detection from
     the diagnostics screen when hardware changes (eGPU, new drivers).
- **OS:** Windows + macOS via the platform adapter (seed exists:
  `core/launcher/platform_adapter.py`). Windows-only code (pycaw, WebView2,
  startup registry) isolated behind it during Tracks A–B as a side effect of
  the skill wrappers and Core API — so the port is contained, not a rewrite.
  Apple Silicon is the flagship GPU case: unified memory + llama.cpp Metal.

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
10. **New:** nothing consumes the core except through the Core API once it
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
| Groq teacher permanent by inertia | consult rate tracked in `BENCHMARKS.md`; M36 exit requires it declining; retirement date is Satvik's explicit call |
| Platform work sneaks in early | Horizon is parked; only isolation-behind-adapters allowed in A–B |
