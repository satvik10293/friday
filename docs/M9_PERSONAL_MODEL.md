# M9 — Personal Model & User Intelligence System

> Strangler-fig, **completely additive**. No M1–M8 file was modified. One new
> package: `core/user_model/`. **Test status: 480 passed**
> (M1 20 · M2 27 · M3 44 · M4 33 · M5 74 · M6 71 · M7 88 · M8 50 · **M9 73**).
> 100% local, privacy-first — the user owns all data; no cloud, no telemetry.

M9 turns FRIDAY from a generic assistant into a **personalized companion** that
understands its primary user: who they are, what they care about, how they work,
how they like to be spoken to, and what they're building — then uses that to
personalize knowledge, prioritize goals, and explain *why*.

---

## What it learns (and never oversteps)

| Engine | Module | Learns | Privacy stance |
|---|---|---|---|
| Profile | `user_profile.py` | name, education, interests, skills, projects, long/short-term goals | versioned, user-owned, fully editable |
| Preferences | `preferences.py` | UI / coding / learning / communication preferences (auto-learned from repeated signals) | only from signals the user produces |
| Habits | `habits.py` | *when* the user does activities (coarse part-of-day buckets) + confidence | **only from activity the user reports** — no surveillance, low time-resolution |
| Interests | `interests.py` | topics + weights + an interest graph + evolution over time | from expressed interest only |
| Projects | `project_tracker.py` | active/paused/completed projects, milestones, linked goals/knowledge/memories | user-owned |
| Communication | `communication_model.py` | detail level · technical depth · structure · terminology | learned dials, adaptable |
| Learning | `learning_profile.py` | visual / step-by-step / example-driven / deep-dive style | from conversation observations |
| Relationship | `relationship_memory.py` | approved long-term facts | **approval-gated**; sensitive data never stored automatically |

---

## Architecture

```
                         UserModelService  (facade + observability + runtime)
                                  │
   ┌──────────┬──────────┬───────┼────────┬────────────┬───────────┬──────────────┐
 Profile  Preferences  Habits  Interests  Projects  Communication  Learning   Relationship
   │          │          │        │          │            │           │             │
   └──────────┴──────────┴────────┴──────────┴────────────┴───────────┴─────────────┘
                                  │   (all over one local SQLite store)
                       ┌──────────┴───────────┐
              PersonalIntelligence      UserContextBuilder
              (explainable rerank)      (UserContextPackage)
                       │                        │
            M8 Knowledge · M4 Goals · M2 Memory (injected, additive)
```

- **`store.py`** — `UserModelStore` over `data/user_model.db`: per-thread conns,
  WAL, `schema_version` gate (same standard as M2/M4/M5/M7). 11 domain tables +
  events + metrics. Never leaves the machine.
- **`service.py`** — `UserModelService`: composes every engine, holds *injected*
  references to M2 Memory / M4 Goals / M7–M8 Knowledge (no edits to those), emits
  `UserModelEvent`s on the runtime bus, exposes `metrics()`/`health()`/`attach()`.
  `get_user_model_service()` singleton.

---

## Personal Intelligence Engine (`personal_intelligence.py`)

- **`build_understanding()`** — a compact snapshot: top interests, active projects,
  strong preferences, communication & learning style, discovered habits.
- **`suggest_knowledge(query)`** — searches M8 knowledge and **re-ranks by the
  user's interests + active projects**, returning `Recommendation`s each carrying
  `Evidence` (the exact signal + weight behind every boost).
- **`goal_relevance` / `prioritize_goals`** — personalised goal ranking (M4 goals
  blended with interest alignment).
- **`personalize_response(text)`** — attaches communication/learning style hints.
- **`explain(query)`** — answers *"Why did you recommend this?"* with the full
  evidence trail. **Explainability is a hard requirement, met in code.**

> Interest integration in action: the user is interested in *Python* → Python
> knowledge gains an attention boost and ranks first, with evidence
> `interest: matches your interests (+0.85)`.

---

## User Context Builder (`user_context.py`)

`UserContextBuilder.build(query)` assembles a **`UserContextPackage`**: profile
summary, personalised goals (M4), active projects, strong preferences, interest
list, interest/project-boosted knowledge (M8), and relevant memories (M2). It is
the personal lens consumed by the **Executive Brain**, **Knowledge System**, and
**Agent Team**.

`augment_context_package(pkg, query)` folds the personal context into an existing
M5 `ContextPackage` (via its public `world`/`lessons`/`memories` fields) — so the
Executive Brain reasons with user context **without any M5 edit**.

---

## Dashboard APIs (`dashboard.py`) — data only, for M10

`UserDashboard` returns JSON-serialisable widget payloads (no UI): active projects,
active goals, learning progress, interests, knowledge growth, communication style,
personal statistics. Ready for M10 Mission Control to render.

---

## Observability

`UserModelEvent` (str-enum bus keys, no `Signal` edit):
`user.profile.updated`, `user.preference.changed`, `user.interest.grown`,
`user.habit.discovered`, `user.project.updated`, `user.learning.adapted`.
Every mutating action records a metric + a `user_events` row and emits the event;
`service.metrics()` aggregates counts; `service.health()` is registered via
`attach(runtime)`.

---

## Privacy guarantees (by construction)

- **Local-only:** all state in `data/user_model.db`; no network code anywhere in
  the package.
- **No telemetry / ads / external sharing.**
- **Approval gate:** long-term relationship facts are inactive until `approve()`;
  anything `sensitive` is never auto-stored.
- **Reported-only habits:** habit detection consumes only activity the user
  explicitly records — no background watching, deliberately coarse time buckets.
- **User-owned & editable:** profile is versioned with full history and `revert`.

---

## How to run the tests

```powershell
# M9 only
.\.venv\Scripts\python.exe -m pytest tests/test_user_profile.py tests/test_preferences.py `
  tests/test_habits.py tests/test_interests.py tests/test_project_tracker.py `
  tests/test_personal_intelligence.py tests/test_user_context.py -q

# full suite — 480 passed
.\.venv\Scripts\python.exe -m pytest -q
```

---

## Success criteria

| Criterion | Delivered by |
|---|---|
| Understand the user | `ProfileManager` + `build_understanding` |
| Track long-term goals | profile `long_term_goals` + M4 integration |
| Track projects | `ProjectTracker` |
| Learn preferences | `PreferenceEngine` (auto from signals) |
| Learn communication style | `CommunicationModel` |
| Build personal context | `UserContextBuilder` → `UserContextPackage` |
| Personalize knowledge retrieval | `PersonalIntelligence.suggest_knowledge` (interest/project boost) |
| Improve recommendations | evidence-weighted re-ranking |
| Explain personalization decisions | `PersonalIntelligence.explain` (+ `Evidence`) |
| Remain completely local & private | local SQLite, approval gate, no cloud/telemetry |
