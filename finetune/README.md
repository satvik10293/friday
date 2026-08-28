# Friday persona fine-tuning dataset

This folder holds the **training data** for giving an open base model Friday's
voice and behaviour. It is deliberately **outside `data/`** (which is her live
memory/state, protected from edits) — this is build material, not her mind.

## What's here

| File | What it is |
|---|---|
| `friday_persona.jsonl` | 76 seed examples, Alpaca schema (`instruction` / `input` / `output`). LitGPT reads this directly. |
| `friday_system_prompt.txt` | The persona anchor (her identity, voice, values), drawn from `core/persona/friday_psyche.py`. |
| `to_chat.py` | Converts the seed file to chat-message schema (`friday_persona_chat.jsonl`) for HuggingFace / TRL. Std-lib only. |

## What this does and does NOT do (read this)

- **Does:** teach a capable base model to *sound and behave* like Friday —
  direct, warm, sharp, partner-mode ("we"), local-first, honest, safety-aware.
- **Does NOT:** teach her facts. Knowledge comes from her existing retrieval
  (memory + knowledge stores), not from fine-tuning. Don't put facts here.
- **Does NOT:** create raw intelligence. That is inherited from the base model's
  pretraining. This is a **thin personality layer** on a borrowed brain.

## This is a SEED, not the finished set

76 examples is enough to *shift tone*, not to fully lock a persona. For a solid
result grow it to a few hundred–~1,000, keeping the same voice: short replies,
"we", opinions, honest deferral, ask-before-risky. Quality beats quantity —
one off-voice example teaches the wrong thing.

## The pipeline (train in the cloud, think locally)

Cloud is the gym, your machine is the home. Nothing here downloads a model.

1. **Prep (local, done):** this dataset.
2. **On Lightning.ai (GPU):** fine-tune a base model with LoRA. Recommended base:
   `Qwen2.5-3B-Instruct` — it matches what `core/intelligence/local_reasoner.py`
   already expects. Using LitGPT:
   ```bash
   pip install 'litgpt[all]'
   litgpt download Qwen/Qwen2.5-3B-Instruct
   litgpt finetune_lora Qwen/Qwen2.5-3B-Instruct \
       --data JSON --data.json_path finetune/friday_persona.jsonl \
       --data.val_split_fraction 0.1 --train.epochs 3 \
       --out_dir out/friday-qwen
   litgpt merge_lora out/friday-qwen/final
   ```
   (Or HuggingFace + PEFT/TRL using `friday_persona_chat.jsonl` from `to_chat.py`.)
3. **Export to GGUF** (so llama.cpp can run it), quantized to `q4_k_m`.
4. **Download** the single `.gguf` file to this machine.
5. **Run locally:** drop it where `LocalReasoner` looks (see `_DEFAULT_FILE` in
   `core/intelligence/local_reasoner.py`), `pip install llama-cpp-python`, and she
   reasons on-device in her own voice — no cloud in the hot path.

## Honest expectations

A persona LoRA on a 3B model gives a **consistent local Friday voice** with the
base model's reasoning. It will not rival frontier cloud models, and it won't add
knowledge. It's a real, achievable win — a local brain that talks like her — not
a leap in raw capability. The capability leap still needs bigger models / more
compute / far more data.
