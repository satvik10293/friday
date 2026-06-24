# HashingEmbedder (embeddings, builtin)

The dependency-free fallback embedder (256-dim, md5 bag-of-words) defined in
`core.memory.embedder.HashingEmbedder`. Deterministic and stable across processes,
so it's the default test backend and the current default for
`core.knowledge.knowledge_index`. No weights, no download. **Milestone:** M2.
