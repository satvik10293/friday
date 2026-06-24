# all-MiniLM-L6-v2 (embeddings)

The production text embedder (384-dim) for M2 semantic memory. Selected by
`core.memory.embedder.get_embedder()` when `sentence-transformers` is installed.

- **Weights:** downloaded on first use — **gitignored**. **Milestone:** M2.
- **Note (see ARCHITECTURE_REVIEW §2.3):** the M7/M8 `KnowledgeIndex` currently
  defaults to the hashing embedder, so this model does **not** yet apply to
  knowledge search — a known follow-up.
