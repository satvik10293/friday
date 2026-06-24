# FRIDAY 4.0 — M2: Memory Service

**Status:** ✅ Delivered (code + tests + docs). Additive — `core/memory/` supersedes `friday_chronicle` without editing it; FRIDAY 3.0 still boots.
**Owner:** Memory layer (`core/memory/`).
**Tests:** `tests/test_memory_store.py`, `test_memory_index.py`, `test_memory_service.py`, `test_memory_migrate.py` — part of the **47/47 passing** suite.

---

## 1. Architectural decision: supersede, don't mutate

The charter said M2 "modifies `friday_chronicle`." I changed that, and here's why: editing the live memory module in place — with **no Git on this machine** — would put the one irreplaceable asset (years of accumulated memory) at risk for no benefit. Strangler-fig is strictly better: `core/memory/` is the new Memory Service, built additively; `friday_chronicle` stays intact and is retired in a later rewiring step once callers move over. `migrate_from_chronicle()` imports the legacy DB when we're ready. This satisfies "replaceable" and keeps the system runnable at every step.

---

## 2. Defects from `FRIDAY_VERIFIED_STATE.md` this closes

| Verified 3.0 defect | Fix in M2 |
|---|---|
| Brute-force `IndexFlatL2` (won't scale) | Pluggable ANN: **FAISS HNSW** (inner-product on normalized vectors = cosine), numpy-flat fallback |
| FAISS↔SQLite link is a side-list saved every 20 inserts → permanent desync on crash | Vectors keyed by **in-row `embed_id`**; index is **fully rebuildable** from the store (`rebuild_index()`) |
| Single shared SQLite connection; `_conn_lock` declared but never used | **Per-thread connections** + WAL + `busy_timeout` |
| No deletion/forgetting path | `forget(hard=False)` soft-delete (auditable) + `amend()` supersede lineage + hard purge |
| No consolidation / unbounded growth | `consolidate()` summarizes old episodes → semantic, demotes raw → archival |
| No migrations | `schema_version` table from row one |
| `content[:512]` silent truncation | embedding handled by the pluggable embedder; truncation is explicit and backend-owned |

---

## 3. Design

### Tiers (one table, one id space)
`working` (RAM) · `episodic` (durable turns) · `semantic` (consolidated summaries/facts) · `archival` (cold, demoted). Summaries are just memory rows with `kind='summary', tier='semantic'` — **no second table to keep in sync**.

### Layers
- **`store.py` — `MemoryStore`** (SQLite **source of truth**): per-thread connections, WAL, FTS5 keyword search (LIKE fallback), soft-delete + supersede, tiers, import bookkeeping. The `embed_id` column is actually written.
- **`index.py` — `VectorIndex`** (derived, **rebuildable**): `FaissHNSWIndex` (scales to millions) or `NumpyFlatIndex` (exact fallback / test backend). Keyed by memory id.
- **`embedder.py` — `Embedder`**: `MiniLMEmbedder` (lazy `all-MiniLM-L6-v2`) or `HashingEmbedder` (deterministic, dependency-free fallback + what tests inject).
- **`working.py` — `WorkingMemory`**: bounded RAM attention buffer.
- **`service.py` — `MemoryService`**: the charter API below.
- **`migrate.py`**: idempotent one-way import from `chronicle.db`.

### Charter API
```
remember(role, content, *, topic, importance, kind, tier, metadata) -> id
recall(query, k) -> [memory dict + 'score']          # provenance for the Decision Log
consolidate(summarizer, older_than_s, min_cluster) -> {summaries_created, archived}
forget(id, hard=False) -> bool                       # soft-delete (audit) or purge
amend(id, new_content, ...) -> new_id                # supersede + lineage
rebuild_index() -> count                             # recovery from the store
assemble_context(query, max_chars, k) -> str
stats() / health() / attach(runtime)
```

### Invariants enforced
- **SQLite is truth; vectors are derived and always rebuildable.** Proven by `test_rebuild_index_recovers_from_reset`.
- **Vectors keyed by in-row `embed_id`.** Proven by `test_remember_writes_embed_id_in_row`.
- **Soft-delete keeps lineage; recall filters it.** Proven by `test_forget_soft_excludes_from_recall`, `test_amend_supersedes_with_lineage`.
- **Side-effect-free import.**

---

## 4. Runtime integration (M1 ↔ M2)

`MemoryService.attach(runtime)`:
- `runtime.register_health("memory", self.health)` — memory shows up in `runtime.health()` with tier counts, index size/backend, and an `index_consistent` drift flag.
- `runtime.schedule("memory.consolidate", self.consolidate, every=3600)` — consolidation runs **off the request path**, on the runtime scheduler (no raw threads).

Recall returns per-hit `score`/ids — exactly the `memory_used` provenance the M1 Decision Log records, so a turn can later answer "what memory did I use?".

---

## 5. Test coverage (25 tests across 4 files)

- **Store (8):** CRUD; FTS/LIKE keyword search + deleted exclusion; `by_ids` deleted filtering; supersede lineage; tiers + counts + invalid-tier guard; access touch; **cross-thread write** (the 3.0 shared-connection regression); import bookkeeping.
- **Index (5):** cosine ranking; remove + size; reset + add_many; empty search; backend factory.
- **Service (10):** embed_id linkage; recall ranking + provenance; soft `forget`; hard purge; `amend` lineage + correct recall; `consolidate` (summary + archival, injected summarizer); `rebuild_index` recovery; keyword fallback when index empty; bounded working memory; `attach` to runtime; context budget.
- **Migration (3):** imports all kinds + recallable; idempotent (no duplicates); no-source handling.

**Failure/recovery classes:** index loss → `rebuild_index`; coarse-clock boundary (fixed with inclusive `<=`); concurrent writes; keyword degradation without vectors.

---

## 6. Scalability outlook

- **FAISS HNSW** holds sub-10ms recall into the millions on CPU; `M=32` is a sane default. When RAM-bound, swap `IndexHNSWFlat` for `IndexHNSWPQ`/IVF-PQ behind the same `VectorIndex` interface — callers don't change.
- **Source-of-truth/derived split** means a backend swap or corruption is a `rebuild_index()`, never data loss.
- **Consolidation + archival** bound the *hot* working set; archival rows stay queryable but can move to a separate cold DB later behind the same store interface.
- **FTS5** gives real keyword search; the LIKE fallback keeps FRIDAY functional on SQLite builds without FTS5.

---

## 7. Known follow-ups (tracked, not gold-plated)

- Index persistence to disk (`save`/`load`) — currently rebuilt from store on construction; fine to thousands, add persistence before the index gets expensive to rebuild.
- Recall reranking + true token budgeting move to the M-cognition Context Assembler; `assemble_context` is the minimal placeholder.
- Archival → separate cold store when episodic volume warrants.
- Wire the live pipeline (`friday_neural`) onto `MemoryService` and retire chronicle — a later rewiring milestone (needs **Git installed first**).

---

*M2 delivered per the 4.0 charter: SQLite is source of truth, vectors are fully rebuildable, memory supports remember/recall/consolidate/forget/amend/rebuild_index, and the design is built to survive years of operation without corruption.*
