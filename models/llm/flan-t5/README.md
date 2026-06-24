# flan-t5 (local LLM)

FRIDAY's **local reasoning reader**. Used by `core.brain.friday_local` to answer
from her own knowledge before any cloud fallback (local-first).

- **Provider:** Google · **Format:** HuggingFace `transformers` · **Runs:** CPU
- **Weights:** *not in Git.* `transformers` downloads `google/flan-t5-base` to the
  HF cache on first use. To pin offline, pre-download with
  `from transformers import pipeline; pipeline("text2text-generation", "google/flan-t5-base")`.
- **Config:** see `config.yaml`. **Milestone:** 3.0.
