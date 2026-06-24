# FRIDAY 4.0 — Architecture Review Report (M1–M9)

**Scope:** the additive M1–M9 rebuild (`core/runtime`, `core/memory`, `core/skills`+
`core/security`, `core/goals`, `core/executive`/`context`/`attention`/`world`/`cognition`,
`core/perception`+`core/sensors`, `core/knowledge`, `core/knowledge_portal`,
`core/user_model`). **480 tests green.** Platform: Windows, **CPU-only**, single
Python 3.12 process.

**Status of this document:** a *critical* self-review. It deliberately attacks the
design rather than celebrating it, and it ends with a **binding pre-coding Design
Challenge Gate** (the user's explicit requirement: *challenge the design before
coding*). No code was written or changed to produce this report.

Severity legend: 🔴 high · 🟠 medium · 🟡 low · 🟢 strength.

---

## 1. Strengths 🟢

1. **Strangler-fig additivity actually held.** Nine milestones, zero edits to lower
   layers, 480 tests still green. Integration is by composition/subclass/adapter
   (`PerceptiveBrain`, `WorldFeed`, `ExecutiveKnowledgeBridge`, injected services).
   This is the single biggest risk-reducer in the whole system.
2. **One governed execution path.** Every capability runs through
   `SkillExecutor.execute` (resolve → validate → policy → role → approval → sandbox
   → audit + decision-log + security-log). A single choke point for authorization
   and audit is the right shape.
3. **Observability is not bolted on.** DecisionLog ("why") + str-enum runtime events
   ("what") + metrics + `register_health` recur in every milestone. The system can
   explain its own behaviour — including M9's `Evidence` ("why did you recommend
   this?").
4. **SQLite-as-truth with rebuildable derived layers.** The 3.0 "FAISS↔SQLite
   save-every-20 desync" is structurally fixed: vectors key off the row's
   `embed_id`, so any index is reconstructable. WAL + per-thread connections +
   `schema_version` are applied consistently.
5. **Testability by design.** Side-effect-free imports; dependency-light fallbacks
   (`HashingEmbedder`, `NumpyFlatIndex`) let the whole stack run without heavy ML
   deps. Fixtures isolate every store in `tmp_path`.
6. **Privacy-first M9.** No network code in `core/user_model`; approval-gated
   long-term facts; reported-only habits. The intent is encoded structurally, not
   just documented.

---

## 2. Weaknesses 🟠/🔴

1. 🟠 **Database sprawl — ~10 independent SQLite files** (`decisions, memory, audit,
   security, goals, world, cognition, perception, knowledge, user_model`). There is
   **no cross-DB transaction, no unified backup, and no orchestrated migration**.
   Multi-store operations (learn → knowledge.db → vault → index, or
   project→goal→knowledge links) are **not atomic**; a crash mid-sequence leaves
   stores disagreeing.
2. 🔴 **`schema_version` is a gate with no runner.** Every store inserts version 1
   and never upgrades — there is **no migration code for v2+** (verified: no
   `ALTER TABLE`/`_migrate` anywhere). The first real schema change has no upgrade
   path; today's discipline is a promise, not a mechanism.
3. 🔴 **Knowledge semantic search is keyword-only in practice.** `KnowledgeIndex`
   defaults to `HashingEmbedder` (bag-of-words, dim 256) and **never** uses MiniLM
   even when installed (verified at `knowledge_index.py:33`). So "semantic" search
   over knowledge is really hashed-token overlap; recall on paraphrase is weak. M2
   memory uses `get_embedder()` (MiniLM if present) — so two subsystems embed
   *differently*, and cross-system similarity is not comparable.
4. 🟠 **Heuristic "intelligence."** Validation (`jaccard`/negation regex),
   distillation/`summarize` (longest-sentence selection), learning
   (`extract_lesson` keyword ranking), fusion (`noisy_or`) and consolidation
   (pairwise token overlap) are all rule-based, English-only, and brittle. They are
   fine as scaffolding but will mislabel, mis-merge, and miss contradictions on real
   prose.
5. 🟠 **Swallowed failures hide divergence.** Vault writes, event emits, and runtime
   attach are wrapped in `except Exception: log.debug(...)`. A vault write can fail
   silently while the DB row commits → the "human-readable source of truth" quietly
   drifts from the index. Failures should be surfaced/queued, not whispered to DEBUG.
6. 🟠 **Two "sources of truth" for knowledge.** M7 store doc says *SQLite is truth*;
   the vault doc says *the vault is truth*. Reconciliation is **timestamp-only**
   (`mtime`/`updated_at`), which is a last-writer-wins policy — concurrent edits
   (user edits the note while FRIDAY updates the row) **lose data** with no merge.
7. 🟠 **Global singletons.** `get_*_service()` module globals open default DB paths
   and hold mutable state. In-process they prevent clean reconfiguration and risk
   test-order coupling; across processes they invite `database is locked`.
8. 🟡 **N+1 graph queries.** `KnowledgeGraph.traverse/path` call `neighbors()` per
   node, each a SQL round-trip (`links_for`). Correct, but a query storm on larger
   graphs.

---

## 3. Scalability limits

| Component | Mechanism | Practical ceiling | Why |
|---|---|---|---|
| `NumpyFlatIndex` (memory + knowledge) | exact matmul search; `np.vstack` per add | ~10⁴–10⁵ vectors | search is O(n·d); **add is O(n)** (full matrix realloc) → bulk ingest is effectively **O(n²)** |
| `KnowledgeGraph` BFS | per-node SQL | ~10³–10⁴ nodes | N+1 queries per traversal |
| Knowledge consolidation/validation | pairwise token overlap | ~10³ entries | O(n²) clustering; validator scans up to 500 peers per candidate |
| Portal graph view | JS force sim on `<canvas>` | ~1–2k nodes | O(n²) repulsion every frame in the browser |
| Whole system | single process, threads | one machine | no horizontal scale; see GIL below |
| `user_events` / `profile_history` / `*_history` | append-only | unbounded growth | **no retention/rotation** anywhere |

The honest ceiling: this is a **single-user, single-machine, ten-thousands-of-items**
system. That matches the product (a personal assistant for Satvik) — but nothing
will *fail loudly* at the limit; it will just get slow and RAM-hungry.

---

## 4. CPU bottlenecks

- 🔴 **The GIL is the master bottleneck.** "Workers" in the runtime are *threads*.
  Every CPU-bound op — embedding, FAISS/numpy matmul, fusion scoring, consolidation
  clustering, the cognitive loop's phases — is serialized by one interpreter lock.
  CPU-only + threads means added cores buy almost nothing for compute.
- 🟠 **Embedding** is the heaviest single op when MiniLM is active (~CPU-seconds for
  cold model load, then per-encode cost) and there is **no batching** on the
  knowledge/user paths.
- 🟠 **`NumpyFlatIndex.search`** is a dense matmul over the entire corpus on every
  query; `add` reallocates the whole matrix.
- 🟠 **Cognitive loop coupling.** Phases run on the shared scheduler; a blocking
  phase (an embedding call, a slow sensor) stalls the loop because there's no
  per-phase timeout/offloading.
- 🟡 Validator/consolidator O(n²) passes spike CPU during maintenance windows.

---

## 5. RAM bottlenecks

- 🟠 **Every vector index lives fully in RAM** as float32 (`d·n·4` bytes), and
  `np.vstack` **doubles** the matrix transiently on each grow. Two indexes (memory +
  knowledge), each rebuilt on construction.
- 🟠 **MiniLM resident set (~90–120 MB)** per process if loaded, plus the sentence-
  transformers/torch stack.
- 🟠 **Full-corpus loads for rebuild:** `all_entries(limit=1_000_000)` and
  `_rebuild_index_from_store()` pull everything into memory at once; the portal
  `/graph` builds the entire node/edge list + JSON in memory.
- 🟡 **Connection/handle growth:** `threading.local` connections × ~10 stores ×
  worker threads → many open SQLite handles and WAL files.
- 🟡 Unbounded history/event tables also grow the DB files (disk, then page cache).

---

## 6. Failure modes

1. 🔴 **Silent store/derived divergence.** Crash (or swallowed exception) between
   `store.create` and `index.add`/`vault.write` leaves an entry that is persisted
   but unsearchable or un-mirrored until the next rebuild — and the failure was only
   logged at DEBUG.
2. 🟠 **Cross-DB partial commits.** No two-phase commit across the ten DBs; a
   multi-store workflow interrupted mid-way is inconsistent with no recovery record.
3. 🟠 **Vault on a synced folder.** Default `C:\VAULT\...`; if that's OneDrive/Dropbox,
   external file locking + partial syncs can corrupt notes or fight WAL. No guard.
4. 🟠 **Lock contention.** Singletons opening the same `data/*.db` from multiple
   processes (e.g., portal + spine + a CLI) can exceed `busy_timeout=5000ms` →
   `database is locked` surfacing as a user-visible error.
5. 🟠 **`ThreadSandbox` cannot kill runaway work.** Python can't force-terminate a
   thread; a CPU-bound or `while True` skill that ignores its timeout keeps running
   and holds the GIL. The timeout reports failure but doesn't stop the work.
6. 🟡 **Unbounded external calls.** A future `DocumentationService` fetcher / voice
   TTS has no enforced timeout; a hung socket stalls the caller.
7. 🟡 **No migration path** (see §2.2) → the first schema change is a manual,
   risky, hand-rolled event.

---

## 7. Security risks

1. 🔴 **Unauthenticated Portal write API.** `core/knowledge_portal` exposes
   `POST/PUT/DELETE /knowledge` on `127.0.0.1:5000` with **no auth, no CSRF token,
   no Origin/Host check**. Any local process — or a remote web page via
   **DNS-rebinding/CSRF to localhost** — can create, mutate, or archive FRIDAY's
   knowledge. "Localhost-only" is *not* an authorization boundary.
2. 🔴 **Personal data is plaintext at rest.** `data/user_model.db` (and the vault,
   and memory.db) are unencrypted SQLite. The "privacy-first" guarantee is *no
   network egress*, but **anyone with file/disk access reads everything** — habits,
   interests, relationship facts, projects. No at-rest encryption, no OS-keychain.
3. 🟠 **In-process privilege.** `SkillExecutor` is the right choke point, but
   `ADMIN`/`SYSTEM` skills and the `ThreadSandbox` run **in the same process and
   address space**. A malicious or buggy high-clearance skill can read every other
   subsystem's memory and DB handles. There is no real isolation boundary.
4. 🟠 **Latent path traversal.** `ObsidianVault.read(rel_path)` joins
   `root / rel_path` with **no containment check**. Safe today (callers pass
   scan-derived paths), but the moment a portal endpoint or sync routine accepts an
   externally-supplied path, `..\..\` escapes the vault. Needs a `resolve()`-under-root
   assertion before it's wired to untrusted input.
5. 🟡 **Stored-content sinks.** The portal dashboard renders knowledge via `esc()`
   on current fields (XSS mitigated today), but this is **one careless `innerHTML`
   away** from stored XSS as the UI grows. No CSP header is set.
6. 🟡 **SSRF surface (future).** When real documentation fetchers land, an
   attacker-influenced query/URL could make FRIDAY fetch internal endpoints. Must be
   gated by M3 permissions + an allowlist + timeouts.
7. 🟢 **Done right:** SQL is parameterized throughout; persistence is JSON not
   pickle/eval; secrets moved to gitignored `.env`. Keep it that way.

---

## 8. Future expansion points

1. **Embeddings & index.** Make `KnowledgeIndex` honor `get_embedder()` (so MiniLM
   applies to knowledge too); **persist** indexes to disk and tag them with an
   embedder identity (backend+dim) so a mismatched/loaded model triggers a rebuild
   instead of silent garbage. Add a real ANN (FAISS HNSW) with a rebuild-on-delete
   policy.
2. **LLM behind existing seams.** `ContextPackage`/`UserContextPackage` are already
   LLM-ready; drop a local LLM into `summarize`/`extract_lesson`/`Reasoner` without
   touching call sites.
3. **Storage hardening.** A migration runner keyed off `schema_version`; a unified
   backup/restore; retention/rotation for event/history tables; an at-rest
   encryption option for `user_model.db`.
4. **Process isolation.** Move CPU-bound work (embedding, FAISS, fusion, force
   layout) to subprocesses/native libs to escape the GIL; make `Sandbox` a real
   process/container boundary for `ADMIN`/`SYSTEM` skills.
5. **Portal/Mission Control (M10).** Add auth + CSRF + CSP to the portal *before*
   exposing more write surface; render the M9 dashboard widgets in the HUD.
6. **Respond-pipeline rewiring** (the big one): route the answer path through
   Memory + Goals + Knowledge + `UserContextBuilder`, replacing the 3.0
   `friday_neural`/`friday_world` flow — behind the M3 governed path.
7. **Observability upgrade.** Promote swallowed `log.debug` failure paths to a
   durable "reconciliation queue" + a health degradation signal, so divergence is
   visible and self-healing.

---

## 9. The Design Challenge Gate (mandatory **before** any future coding)

> **Rule:** No M10+ milestone — and no non-trivial change to M1–M9 — may begin
> implementation until it has answered the questions below **in writing** in its
> milestone doc. The design must survive its own attack first. This operationalizes
> the directive to *challenge the design before coding*.

**A. Necessity & blast radius**
- What *exactly* fails today without this? (If nothing, stop.)
- Does it stay additive? Name the seam (adapter/subclass/injection). If it must
  touch M1–M9, justify why no seam exists and what tests pin the old behaviour.

**B. Data & consistency**
- Does it add a DB/table? If so, **why not reuse an existing store?** What's the
  migration (schema_version bump + runner)?
- Which multi-store writes are now possible, and what is the recovery story if it
  crashes mid-sequence? (Idempotent replay? Reconciliation pass?)
- Source-of-truth: if it writes both DB and vault, what is the conflict policy
  beyond last-writer-wins?

**C. Cost at 10× and 100×**
- Big-O of the hot path in CPU **and** RAM. Where's the `O(n²)`? Is anything loaded
  fully into memory?
- Does it run CPU-bound work under the GIL on the request/loop thread? Can it block
  the cognitive loop or the event bus?
- What's the retention policy for anything append-only it creates?

**D. Failure & observability**
- Enumerate failure modes. For each: detected how, surfaced where, recovered how.
  **No `except: log.debug` for anything that can cause divergence.**
- Does every mutating action emit an event + metric + decision-log entry?

**E. Security & privacy**
- New external surface (HTTP, file, network)? Then: authn/authz, CSRF/Origin, input
  validation, path containment, timeouts, SSRF allowlist — which apply, which are
  implemented?
- New personal data? Then: is it local-only, approval-gated, and is at-rest exposure
  acceptable or does it need encryption?

**F. The kill question**
- *"What would make us delete this in six months?"* If the answer is easy, redesign
  before coding, not after.

A milestone that cannot answer A–F is not ready to be written.

---

## 10. Bottom line

The architecture is **well-shaped for what it is**: a governed, observable,
additive, single-user personal assistant, and the discipline has held across nine
milestones. Its real risks are not its structure but its **honest limits made
implicit**: keyword-only knowledge search masquerading as semantic, ten unsynchronized
SQLite files with a migration gate that has no runner, GIL-bound CPU work, swallowed
failures that let the vault and DB drift, and an unauthenticated local write API over
plaintext personal data. None of these threaten the 480-test green state today; all
of them become real the moment the corpus grows, a second process appears, or the
portal is exposed. The fixes are known and mostly additive — and from here, the
Design Challenge Gate (§9) is the mechanism that keeps the next milestone from
quietly turning a limit into a defect.
