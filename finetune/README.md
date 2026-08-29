# Friday persona fine-tuning dataset

This folder holds the **training data** for giving an open base model Friday's
voice and behaviour. It is deliberately **outside `data/`** (which is her live
memory/state, protected from edits) — this is build material, not her mind.

## What's here

| File | What it is |
|---|---|
| `friday_autotrain.jsonl` | **369 examples for Hugging Face AutoTrain** — single `text` column, Qwen ChatML. This is the one to upload. |
| `friday_persona.jsonl` | 369 examples, Alpaca schema (`instruction` / `input` / `output`) — the source of truth. |
| `friday_persona.json` | Same, as a JSON list. |
| `friday_persona_chat.jsonl` | Same, chat-message schema (for HF TRL, or a non-Qwen base). |
| `friday_system_prompt.txt` | The persona anchor (her identity, voice, values), drawn from `core/persona/friday_psyche.py`. |
| `to_autotrain.py` | Renders the source into `friday_autotrain.jsonl` (Qwen ChatML). Std-lib only. |
| `to_chat.py` | Renders the source into `friday_persona_chat.jsonl`. Std-lib only. |
| `wire_local_model.py` | After training, points the local brain at the downloaded GGUF. |
| `EXPORT_AND_RUN.md` | Runbook: trained model → GGUF → running locally. |

## What this does and does NOT do (read this)

- **Does:** teach a capable base model to *sound and behave* like Friday —
  direct, warm, sharp, partner-mode ("we"), local-first, honest, safety-aware.
- **Does NOT:** teach her facts. Knowledge comes from her existing retrieval
  (memory + knowledge stores), not from fine-tuning. Don't put facts here.
- **Does NOT:** create raw intelligence. That is inherited from the base model's
  pretraining. This is a **thin personality layer** on a borrowed brain.

## Dataset size

369 examples — enough to lock a consistent persona. Same voice throughout:
short replies, "we", opinions, honest deferral, ask-before-risky. Quality beats
quantity; one off-voice example teaches the wrong thing. Grow it further only if
a training run shows a specific voice gap.

## The pipeline (train on Hugging Face, think locally)

Hugging Face is the gym, your machine is the home. Nothing here downloads a model.

1. **Prep (local, done):** this dataset.
2. **Train on Hugging Face AutoTrain:** task **LLM Fine-tuning (SFT)**. Upload
   `friday_autotrain.jsonl`, set the text column to `text`, base model
   `Qwen/Qwen2.5-3B-Instruct` (it matches `core/intelligence/local_reasoner.py`).
   Keep LoRA + ~3 epochs. AutoTrain pushes the trained model to a repo on your
   HF Hub. **Enable "merge adapter" / push the merged model** so it converts to
   GGUF cleanly. *(Compute is pay-per-use — a small LoRA is usually a few dollars.)*
3. **Export to GGUF** — download the HF model, convert with llama.cpp, quantize to
   `q4_k_m`. Full commands in `EXPORT_AND_RUN.md`.
4. **Run locally:** `python finetune/wire_local_model.py <file.gguf>`, then
   `pip install llama-cpp-python`. She reasons on-device in her own voice — no
   cloud in the hot path.

## Honest expectations

A persona LoRA on a 3B model gives a **consistent local Friday voice** with the
base model's reasoning. It will not rival frontier cloud models, and it won't add
knowledge. It's a real, achievable win — a local brain that talks like her — not
a leap in raw capability. The capability leap still needs bigger models / more
compute / far more data.
