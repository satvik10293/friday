# M8 — Knowledge & Learning System (+ Knowledge Portal)

> Strangler-fig, **completely additive**. No M1–M7 file was modified. New code only:
> **new files** added to `core/knowledge/` (search · writer · vault_manager · executive
> bridge) and one **new package** `core/knowledge_portal/` (local website).
> **Test status: 407 passed** (M1 20 · M2 27 · M3 44 · M4 33 · M5 74 · M6 71 · M7 88 · **M8 50**).
> 100% local-first; the portal runs entirely offline.

M8 completes FRIDAY's shift from a *memory-driven* system to a *knowledge-driven*
one. M7 built the Knowledge Core (store, graph, validator, learning, vault, service);
**M8 makes it usable**: one unified search cascade, a distillation writer that
produces clean Obsidian notes, a vault organiser, an Executive-Brain seam, and a
local "private Wikipedia" web portal over the whole thing.

> **Why additive instead of recreating `core/knowledge/`?** The M8 brief lists
> `knowledge_store.py`, `knowledge_graph.py`, `knowledge_validator.py`,
> `knowledge_models.py` — but those already exist from M7, and the milestone's hard
> rule is *"Do not modify M1–M7 files."* The stricter rule wins: M8 **reuses** the
> M7 modules and adds only genuinely new files. `KnowledgeItem`≈M7 `KnowledgeEntry`,
> `KnowledgeRelation`/`KnowledgeSource`/`KnowledgeConfidence` map onto the M7 models.

---

## What was added

### `core/knowledge/` — new files (M7 files untouched)

| Module | Role |
|---|---|
| `knowledge_search.py` | `KnowledgeSearch` — the unified retrieval cascade: **Working Memory → Memory Service → Knowledge Store → Knowledge Graph → External**. Returns the first tier that clears a confidence `threshold`; external is consulted only when local confidence is below threshold **and** the caller opts in. `SearchResult` carries the tier, confidence, items, graph-related concepts, an optional external candidate, and the full `trace`. |
| `knowledge_writer.py` | `KnowledgeWriter` — distillation. Turns raw text into a structured `DistilledNote` (`# Title / ## Concept / ## Example / ## Related`), stores it as validated knowledge (M7), generates `[[backlinks]]`, and creates real graph relations to related concepts that already exist. |
| `vault_manager.py` | `VaultManager` — Obsidian organisation over the M7 vault: the standard folder skeleton (`Programming/ Projects/ Goals/ Reflections/ Knowledge/ Daily/`), category→folder routing, note create/update, backlink extraction, and an `integrity_check()` (broken `[[links]]`, missing ids). |
| `executive_bridge.py` | `ExecutiveKnowledgeBridge` — the M5 seam. `search_knowledge`, `store_knowledge`, `build_context` (a knowledge fragment for `ContextPackage`), and `augment_context(pkg, query)` which folds knowledge into a live `ContextPackage` (`world['knowledge']` + merged `lessons`) — **without modifying any M5 file**. |

### `core/knowledge_portal/` — new package (local website)

| Module | Role |
|---|---|
| `portal_api.py` | `PortalAPI` — framework-agnostic REST logic (plain dicts): `list_knowledge`/`get`/`create`/`update`/`delete` (soft = archive), `search`, `graph`, `stats`. Fully testable without a server. |
| `portal_graph.py` | `build_graph(store)` → `{nodes, edges}` for the graph view; category colours, usage-weighted node size, symmetric `related` pairs collapsed to one undirected edge. |
| `portal_ui.py` | `render_dashboard()` → a single self-contained HTML page (no tabs, no CDN): overview stats, most-used concepts, recent knowledge, live search, concept detail, and an interactive **canvas force-graph** (zoom / pan / node selection, Obsidian-style). |
| `portal_server.py` | `PortalServer` — wraps `PortalAPI` + UI in **Flask** (lazy import; localhost-only; `127.0.0.1:5000`). `build_app()`/`run()`/`start_background()`; `get_portal_server()` uses the M7 singleton. |
| `portal_sync.py` | `PortalSync` — durable SQLite ↔ vault reconciliation (`db_to_vault`/`vault_to_db`/`full_sync`), reusing M7 `rebuild_from_vault` + the vault writer. The website reads the API live, so it needs no separate store. |

---

## The three synchronized representations

```
   SQLite (data/knowledge.db)   ← SOURCE OF TRUTH (M7 KnowledgeStore)
        ▲   │  PortalSync.full_sync()
        │   ▼
   Obsidian vault (Markdown)    ← human-readable mirror (M7 vault, M8 VaultManager)
        ▲
        │  reads the API live (no copy)
   Knowledge Portal (website)   ← visual face (M8 core/knowledge_portal)
```

The portal is explicitly **not** a source of truth — it's a visualisation/management
layer. Edits flow through the API into the store (and out to the vault on sync).

---

## Search cascade (local-first, external last)

```
query
  → Working Memory   (M2 buffer)            ─┐
  → Memory Service   (M2/M3 recall)          │ stop at the first tier
  → Knowledge Store  (M7 semantic + keyword) │ that clears `threshold`
  → Knowledge Graph  (M7 related concepts)  ─┘
  → External Sources (M7 DocumentationService) — ONLY if best local confidence
                                                 < threshold AND allow_external
```

External retrieval still obeys the M7 charter: offline by default (injected fetcher),
**summarise before store, never a whole page**, and it returns only an *unstored
candidate* for validation.

---

## Observability

The write/learn/retrieve paths flow through the M7 `KnowledgeService`, so they keep
emitting `KnowledgeEvent`s (`knowledge.created/updated/learned/consolidated/archived/retrieved`)
and recording metrics + history. The portal API surfaces `stats()` and `health()`;
`VaultManager.health()` reports vault integrity; `PortalSync.health()` reports
store/vault counts.

---

## Running the portal

```python
from core.knowledge.knowledge_service import get_knowledge_service
from core.knowledge_portal.portal_server import PortalServer

PortalServer(get_knowledge_service()).run()      # http://127.0.0.1:5000  (blocking)
# or, non-blocking:
PortalServer(get_knowledge_service()).start_background()
```

The dashboard is one page: overview · most-used · recent · search · interactive
graph · concept detail. It works with no internet connection.

---

## How to run the tests

```powershell
# M8 only
.\.venv\Scripts\python.exe -m pytest tests/test_knowledge_search.py tests/test_knowledge_writer.py `
  tests/test_knowledge_validator.py tests/test_knowledge_system.py tests/test_knowledge_portal.py -q

# full suite — 407 passed
.\.venv\Scripts\python.exe -m pytest -q
```

---

## Success criteria

| Criterion | Delivered by |
|---|---|
| Learn knowledge | `KnowledgeWriter.write` + M7 `KnowledgeService.learn/teach` |
| Organize knowledge | `VaultManager` folder routing + M7 categories |
| Link concepts | `KnowledgeWriter._link_related` + M7 `KnowledgeGraph` |
| Maintain Obsidian vault | `VaultManager` (structure + integrity) over M7 `ObsidianVault` |
| Search local first | `KnowledgeSearch` cascade (external gated) |
| Build knowledge graph | `portal_graph.build_graph` + M7 graph |
| Distill into reusable knowledge | `KnowledgeWriter.distill` |
| Use knowledge during reasoning | `ExecutiveKnowledgeBridge.augment_context` → `ContextPackage` |
| FRIDAY publishes knowledge automatically | `PortalAPI.create` / writer → store → vault |
| Browse in a browser | `PortalServer` + `portal_ui` dashboard |
| Obsidian ↔ website synchronized | `PortalSync.full_sync` |
| Knowledge graph visible | `portal_ui` canvas force-graph |
| Works entirely offline | self-contained UI, localhost Flask, no CDN/cloud |
