# M10 — Design Challenge Gate (Review System)

> Operationalises `docs/ARCHITECTURE_REVIEW.md §9`: a milestone must survive its own
> design challenge **before** implementation begins. New additive package
> `core/review/`. **Tests: `tests/test_design_gate.py` (10).**
>
> Also covers **Part 5 — Knowledge Retrieval Hardening** (the embedding abstraction
> + retrieval pipeline), since both are about raising quality before scale.

---

## The gate (`core/review/design_gate.py`)

A `DesignReview(milestone)` must answer eight questions; the `DesignGate` evaluates
it and only a complete, substantive, additive review **passes**.

| # | Question (`DesignQuestion`) |
|---|---|
| 1 | Why does this exist? |
| 2 | What breaks without it? |
| 3 | What fails if it crashes? |
| 4 | What happens at 100× scale? |
| 5 | What are the security risks? |
| 6 | What are the performance risks? |
| 7 | Would we remove this in six months? |
| 8 | Can this be simplified? |

`evaluate()` reports `missing` (unanswered), `weak` (too thin), and a pass/fail;
`submit()` records a passing review (optionally persisted to JSON). Non-additive
changes are blocked by default (the M-series charter). **No milestone implementation
begins until its review passes.**

### M10 cleared its own gate

M10 was run through the gate before this writeup — all eight answered, additive,
`passed: True` (see the changelog entry). A sample answer:

> **What fails if it crashes?** *Mission Control degrades panel-by-panel via
> `safe_call`; the cockpit and FRIDAY keep running. Auth/migration failures are
> isolated and audited.*

---

## Part 5 — Knowledge Retrieval Hardening

Closes the review's "knowledge search is keyword-only / embedder hardcoded" risk.

### Embedding abstraction — `core/embeddings/`
`EmbeddingRegistry` resolves backends **by name**, none hardcoded:

| Backend | Model | Dim | Needs |
|---|---|---|---|
| `hashing` | deterministic bag-of-words | 256 | nothing (always available) |
| `minilm` | all-MiniLM-L6-v2 | 384 | sentence-transformers |
| `bge-small` | BAAI/bge-small-en-v1.5 | 384 | sentence-transformers |
| `nomic` | nomic-ai/nomic-embed-text-v1 | 768 | sentence-transformers |

`resolve_backend_name(explicit?)` picks **explicit arg → `FRIDAY_EMBEDDING_MODEL`
env → best available** (quality first, hashing as the guaranteed fallback). Models
load lazily; new backends register via `EmbeddingRegistry.register` without touching
call sites.

### Retrieval pipeline — `core/retrieval/`
`SemanticSearch` runs the full local-first cascade with real vector similarity (not
the keyword-only path), measuring quality:

```
Working Memory → Memory → Knowledge DB → Semantic Search → Knowledge Graph → External
```

`RetrievalMetrics` tracks search latency, result confidence, embedding quality
(top-score), hit rate, and **retrieval accuracy** (precision@k via `evaluate()`),
feeding the Mission Control knowledge/resource panels. The embedder is injected —
the same query is keyword-only with `hashing` and semantic with `bge-small`/`minilm`
without any code change.

---

## Standing rule

Every future milestone (M11–M14) ships a passing `DesignReview` in its milestone
doc before code is written. The gate is the mechanism that keeps a known limit from
quietly becoming a defect.
