# FRIDAY — Model Storage & Registry

This directory is the **version-controlled registry of every model FRIDAY uses**.
It holds *configuration, metadata, and documentation* — **never** the binary
weights. Weights are large, regenerable, and machine-local; configs are small,
human-readable, and must be reproducible.

> **Rule:** Git stores how a model is *configured and used*. Git never stores the
> model's *weights*. See `../.gitignore` for the exclusion list.

## Layout

```
models/
  registry.json          # machine-readable registry (the source of truth for tooling)
  MODEL_REGISTRY.md      # human-readable index
  README.md              # this file
  llm/        <name>/     metadata.json · config.yaml · README.md
  vision/     <name>/     metadata.json · config.yaml · README.md
  speech/     <name>/     metadata.json · config.yaml · README.md
  embeddings/ <name>/     metadata.json · config.yaml · README.md
```

Each model folder contains exactly three tracked files:

| File | Purpose |
|---|---|
| `metadata.json` | identity: provider, format, source (local/cloud/api), milestone introduced, version, whether weights are tracked, where weights live, what uses it |
| `config.yaml` | runtime configuration (the knobs FRIDAY loads/passes) |
| `README.md` | what the model is, how to obtain its weights, notes |

## In Git vs. excluded

**In Git:** model configs, agent definitions, system prompts, personality settings,
routing rules, brain architecture, model metadata, this registry, training notes,
documentation, and Obsidian knowledge about models.

**Excluded** (via `.gitignore`): `.gguf`, `.bin`, `.pt`, `.pth`, `.safetensors`,
`.onnx`, `.h5`, `.ckpt`, large datasets, embedding/FAISS databases, and caches.
The one tracked weight is the small bundled MediaPipe gesture model
(`core/io/models/hand_landmarker.task`, ~7 MB) the app needs to boot.

## Querying model version history

`core.infra.model_registry.ModelRegistry` reads this registry; `core.infra.repo_status`
answers, from Git history, *when a model was added, when it was modified, which
milestone introduced it, and which commit changed it* — and provides the repository
snapshot a future Mission Control will display.
