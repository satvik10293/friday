# FRIDAY Model Registry

Human-readable index of every model FRIDAY uses. The machine-readable source of
truth is `registry.json`; per-model detail lives in each folder's `metadata.json`,
`config.yaml`, and `README.md`. **Weights are not in Git** (see `../.gitignore`).

| Model | Category | Provider | Format | Source | Weights in Git | Milestone | Used by |
|---|---|---|---|---|---|---|---|
| flan-t5 | llm | google | transformers | local | no | 3.0 | `friday_local` |
| groq | llm | groq | api | cloud | n/a | 3.0 | `friday_neural` |
| gemini | llm | google | api | cloud | n/a | 3.0 | `friday_neural` |
| openai | llm | openai | api | cloud | n/a | 3.0 | `friday_neural` |
| hand-landmarker | vision | mediapipe | task | local | **yes** (~7 MB) | 3.0 | `friday_gesture` |
| easyocr | vision | jaided-ai | pth | local | no | 3.0 | `friday_visual` |
| faster-whisper | speech | systran | ctranslate2 | local | no | 3.0 | `friday_stt` |
| edge-tts | speech | microsoft | api | cloud | n/a | 3.0 | `friday_tts` |
| all-minilm-l6-v2 | embeddings | sentence-transformers | transformers | local | no | M2 | `memory.embedder` |
| hashing | embeddings | friday | builtin | local | no | M2 | `memory.embedder`, `knowledge_index` |

## Routing

`llm/routing.yaml` holds the version-controlled brain-routing rules (local-first:
`flan-t5 → Groq → Gemini → OpenAI`).

## Version history

Every model's add/modify history is traceable through Git:

```powershell
git log --follow -- models/llm/flan-t5            # when added / modified, which commits
git log --oneline --all -- models/                 # all model-registry changes
git tag --list "m*"                                 # milestone checkpoints
```

`core.infra.repo_status` exposes the same answers programmatically (branch, latest
commit, modified files, per-model history) for a future Mission Control panel.
