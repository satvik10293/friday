# Model Storage & Git Versioning

A standing FRIDAY requirement: **the intelligence system must be reproducible and
recoverable from Git** — every configuration that defines *how FRIDAY thinks* is
version-controlled, while the heavy, regenerable model weights are not.

---

## Principle

> Git stores how FRIDAY is **configured and behaves**. Git never stores model
> **weights**. Configs are small, human-readable, and reproducible; weights are
> large, regenerable, and machine-local.

### Stored in Git
Model configurations · agent definitions · system prompts · personality settings ·
routing rules · brain architecture · model metadata · the model registry · training
notes · documentation · Obsidian knowledge about models.

These already live in the tree: `models/` (registry + per-model config/metadata),
`models/llm/routing.yaml` (brain routing), `core/persona/` (identity/mood),
`core/agents/` (agent definitions), `friday_config.json` (non-secret settings),
and `docs/`.

### Excluded from Git (via `.gitignore`)
`.gguf` · `.bin` · `.pt` · `.pth` · `.safetensors` · `.onnx` · `.h5` · `.ckpt` ·
large datasets · embedding/FAISS databases (`*.faiss`, `*.index`) · caches ·
downloaded HF weights. **One exception:** the small (~7 MB) bundled MediaPipe
gesture model `core/io/models/hand_landmarker.task`, which the app needs to boot.

---

## Model directory

```
models/
  registry.json        # machine-readable registry (source of truth for tooling)
  MODEL_REGISTRY.md    # human-readable index
  README.md            # conventions
  llm/        flan-t5/ · groq/ · gemini/ · openai/ · routing.yaml
  vision/     hand-landmarker/ · easyocr/
  speech/     faster-whisper/ · edge-tts/
  embeddings/ all-minilm-l6-v2/ · hashing/
```

Each model folder holds exactly: `metadata.json`, `config.yaml`, `README.md`.

---

## Git checkpoints (convention)

Commit at these points, with the milestone in the message:

- **Before** milestone work begins
- **After** milestone completion (`git commit -m "M10 complete"`)
- **Before** a major refactor
- **After** successful testing (suite green)

Tag milestone completions so they're easy to find and diff:

```powershell
git commit -m "M10 complete"
git tag -a m10-complete -m "M10 — Mission Control"
```

The repository was initialised at the M1–M9 baseline (tag `m9-baseline`); the
500-test green state is the recovery point this convention protects.

---

## Version history — what FRIDAY can answer

Every model change is traceable through Git. `core.infra.repo_status.RepoStatus`
exposes it programmatically:

| Question | How |
|---|---|
| When was this model added? | `RepoStatus.file_added("models/llm/flan-t5/metadata.json")` → first commit |
| When was it last modified? | `RepoStatus.file_last_modified(path)` |
| Which milestone introduced it? | `ModelRegistry.milestone_of("flan-t5")` (+ milestone tags) |
| Which commit changed it? | `RepoStatus.file_history(path)` → hash + subject + date |
| What models exist / by category? | `ModelRegistry.list_models()` / `by_category()` |

CLI equivalents:

```powershell
git log --follow -- models/llm/flan-t5      # add/modify history of a model
git tag --list "m*"                          # milestone checkpoints
```

`core.infra.model_registry.ModelRegistry` reads `models/registry.json` (merging
each model's on-disk `metadata.json`) and is fully unit-tested; `RepoStatus` shells
out to **read-only** `git` with fixed arguments, never interpolating input into a
command, and degrades gracefully to `{available: False}` when Git is absent or the
directory is not a repo.

---

## Future — Mission Control (M10)

The "Repository health" panel will render, from `RepoStatus.status()` +
`ModelRegistry`:

- current Git branch · latest commit · modified files
- model versions (per the registry) · milestone tags
- repository health (clean/dirty, versioned/unversioned)

so the whole intelligence system stays reproducible and recoverable at a glance.
The read-only data layer for this already exists (`core/infra/repo_status.py`,
`core/infra/model_registry.py`); only the UI remains for M10.

---

## Tests

- `tests/test_model_registry.py` (10) — registry load/query/health, custom registry,
  graceful missing registry, side-effect-free import.
- `tests/test_repo_status.py` (10) — branch/commit/dirty/modified, **file add vs.
  modify history**, milestone tags, status payload, graceful when not a repo,
  pathspec-not-an-option safety. (Skip cleanly if Git is unavailable.)
