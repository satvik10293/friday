# M7 — Knowledge & Learning Core

> Strangler-fig, **completely additive**. No M1–M6 file was modified. One new
> package built out: `core/knowledge/` (the legacy 3.0 `__init__.py` docstring is
> left untouched; consumers import the M7 submodules directly).
> **Test status: 357 passed** (M1 20 · M2 27 · M3 44 · M4 33 · M5 74 · M6 71 · **M7 88**).
> 100% local-first — external knowledge is the *last* resort, never the first, and
> is always summarised before storage.

M7 gives FRIDAY a mind that *accumulates understanding*. Where **memory** (M2/M3)
records *what happened*, **knowledge** records *what is true* — distilled concepts,
coding patterns, and lessons she can recall, relate, validate, consolidate, and
explain. The **Obsidian vault** is the permanent, human-owned source of truth; the
SQLite store and vector index are rebuildable projections of it.

---

## Storage hierarchy (source of truth → rebuildable cache)

```
   Obsidian vault (Markdown notes)          ← SOURCE OF TRUTH, user-owned/editable
        │  scan / re-index
        ▼
   knowledge.db (SQLite store + metadata)   ← rebuildable index
        │  embed
        ▼
   KnowledgeIndex (vectors: numpy / FAISS)  ← rebuildable retrieval cache
```

Either derived layer can be reconstructed at any time: `rebuild_from_vault()`
re-reads the notes; `_rebuild_index_from_store()` re-embeds from SQLite. User edits
in the vault always win (`ObsidianVault.write` refuses to clobber a note whose
on-disk `updated_at` is newer, unless `force=True`).

---

## Read path — local-first, external last

```
answer(query, allow_external=False)
  → search_knowledge()  : semantic (vector) + keyword backfill over local store
  → if hits             : return {source: 'local'}
  → if not allow_external: return {source: 'none'}          ← default: never leaves the box
  → DocumentationService.lookup()                            ← only here does external happen
        → local_lookup first (again)
        → fetcher(query)   (injected; None by default ⇒ offline)
        → summarize()      (distil to a few sentences — NEVER store a whole page)
        → return a *candidate* (unstored) for validation
```

> **Charter rule, enforced in code:** *"Never search externally first. Always search
> local last-resort only. External information must be summarised before storage.
> Never store entire pages."* The `DocumentationService` has no network code of its
> own — it calls an **injected** `fetcher`, which is `None` unless the caller opts in.

---

## Packages & modules — `core/knowledge/`

| Module | Role |
|---|---|
| `knowledge_models.py` | `KnowledgeEntry` (distilled understanding) + `KnowledgeCategory`, `KnowledgeRelation`, `KnowledgeStatus`, `KnowledgeLink`, `ValidationReport`, `ConsolidationResult`; `slugify`, `new_knowledge`. Pure data, fully serialisable. |
| `knowledge_store.py` | `KnowledgeStore` — SQLite source-index (`data/knowledge.db`). Per-thread conns + WAL + `schema_version` gate. Tables: `knowledge`, `knowledge_links`, `knowledge_history`, `knowledge_metrics`. CRUD, text search, links, history, metrics, counts/health, export/import. |
| `knowledge_graph.py` | `KnowledgeGraph` — relationship engine over `knowledge_links`. `related` (symmetric) + `parent`/`child` (inverse pairs); `neighbors`/`traverse`/`path`/`explain` (`Python → Flask → Authentication`). |
| `knowledge_index.py` | `KnowledgeIndex` — semantic retrieval cache. Reuses M2 `HashingEmbedder` + `NumpyFlatIndex`/FAISS by composition; owns a str↔int id map. `add`/`remove`/`search`/`rebuild`/`reset`. |
| `knowledge_validator.py` | `KnowledgeValidator` — quality gate before storage. Detects duplicates, contradictions (opposite polarity on a shared subject), outdated/superseded entries, and low confidence → `ValidationReport` with `store`/`update`/`reject`. |
| `learning_engine.py` | `LearningEngine` — turns experience into knowledge. `extract_lesson`, `learn_from_memories`, `promote_memory`, `promote_reflection`. Rule-based, local (the *TemplateNotFound* lesson). |
| `coding_knowledge.py` | `CodingKnowledge` — curated, *distilled* patterns (Flask auth, SQLite-per-thread, retry/backoff, error handling). `patterns`/`seed` (idempotent)/`find`. |
| `documentation_service.py` | `DocumentationService` — the sanctioned, last-resort external bridge. Local-first lookup order; injected/optional `fetcher` (offline by default); `summarize` distils before any storage. |
| `knowledge_consolidator.py` | `KnowledgeConsolidator` — clusters overlapping entries, writes one summary, archives the originals (never deletes), records lineage. |
| `vault.py` | `ObsidianVault` — Markdown adapter (YAML front-matter + body + `[[links]]`). `render`/`parse`/`write`/`read`/`scan`/`changed_since`; preserves manual edits. |
| `knowledge_service.py` | `KnowledgeService` — public API composing all of the above. `KnowledgeEvent` str-enum; `get_knowledge_service()` singleton. |

---

## `KnowledgeService` — the public API

| Method | Purpose |
|---|---|
| `remember_knowledge(...)` | Validate → store → index → vault. Duplicates **refine in place** instead of creating twins; low-confidence is rejected. |
| `teach(title, content)` | Explicit user knowledge — trusted, stored without rejection (`source="user"`). |
| `learn(text)` | Distil a lesson from experience text and store it (validated). |
| `search_knowledge(query, k)` | Local semantic + keyword search; touches usage counts. |
| `answer(query, allow_external=False)` | Local-first resolution; external only on explicit opt-in. |
| `promote_memory` / `promote_reflection` / `learn_from_goal` | **Additive integration hooks** — fold M2/M3 memories and M4 goal reflections into knowledge without touching those modules. |
| `relate` / `explain` | Graph relationships and human-readable connection chains. |
| `consolidate` / `archive` / `seed_coding_patterns` | Maintenance. |
| `rebuild_from_vault` | Reconstruct store + index from the vault (user edits win). |
| `validate` / `stats` / `health` | Diagnostics. |
| `attach(runtime)` | Wire into the M1 runtime: health probe + periodic consolidation. |

**Observability:** every mutating action records `knowledge_history` + a metric and
emits a `KnowledgeEvent` (`knowledge.created/updated/learned/consolidated/archived/retrieved`)
on the M1 runtime bus — the str-enum pattern from M4/M5/M6, so the frozen 3.0
`Signal` enum is never edited.

---

## Knowledge vs Memory

| | Memory (M2/M3) | Knowledge (M7) |
|---|---|---|
| Stores | experiences, conversations | distilled understanding |
| Truth | "this happened at time T" | "this is how X works" |
| Lifecycle | decays / consolidates by recency | validated, related, consolidated by meaning |
| Source of truth | `data/memory.db` | the Obsidian vault (Markdown) |

The bridge is the **LearningEngine**: experiences become knowledge via
`promote_memory` / `promote_reflection`.

---

## Data files

- `data/knowledge.db` — SQLite store/index (rebuildable from the vault).
- Obsidian vault — `FRIDAY_KNOWLEDGE_VAULT`, default `C:\VAULT\friday_knowledge`
  (one Markdown note per entry; the permanent, user-owned record).
- Vector index — in-memory, rebuilt from the store on construction.

---

## How to run

```powershell
# all M7 tests (store · graph · index · learning/validator · docs · consolidator/coding · service+vault)
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_store.py tests/test_knowledge_graph.py `
  tests/test_knowledge_index.py tests/test_learning_engine.py tests/test_documentation_service.py `
  tests/test_knowledge_consolidator.py tests/test_knowledge_service.py -q

# full suite — 357 passed
.\.venv\Scripts\python.exe -m pytest -q
```

---

## Compliance with the M7 charter

- **Completely additive** — no M1–M6 file modified; integration is by composition,
  subclass-free adapters (`promote_*`, `learn_from_goal`), and injected dependencies.
  `tests/conftest.py` gained two fixtures (additive only).
- **No regressions** — 269 prior tests still pass; 88 new → **357**.
- **Side-effect-free imports** — every module imports clean; no DB/file/network at
  import time (`data/knowledge.db` is created only when a store is constructed).
- **SQLite remains the source of truth** for structured data; the **vault** is the
  human-owned permanent record above it; vectors are a pure cache.
- **Fully local-first** — external knowledge is opt-in, summarised, never a page dump,
  and the fetcher is `None` (offline) by default.
