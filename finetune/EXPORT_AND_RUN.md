# From fine-tuned model → GGUF → running locally

Step 2 of the plan: after AutoTrain finishes, turn the trained model into a single
`.gguf` file and wire it into FRIDAY's local brain. This is the fiddliest part; the
exact sub-command names drift between tool versions, so if one errors, run it with
`--help` and match the current name.

FRIDAY's `LocalReasoner` (`core/intelligence/local_reasoner.py`) loads
`models/<model_file>` (a llama.cpp GGUF) via `llama-cpp-python`. Goal: produce a
GGUF and point the config at it.

---

## A. Get the trained model from Hugging Face, then convert to GGUF

AutoTrain pushes the fine-tuned model to a repo on your HF Hub. Download it, then
convert HF → GGUF with llama.cpp. (Do this on **this machine** — conversion is
CPU-fine; only training needed the cloud.)

### Download the trained model
```bash
pip install huggingface_hub
huggingface-cli login                      # your HF token
huggingface-cli download <your-username>/<autotrain-repo> --local-dir out/friday-hf
```

### If AutoTrain gave you a LoRA adapter (not a merged model)
Merge it to a full HF model first:
```python
from peft import AutoPeftModelForCausalLM
from transformers import AutoTokenizer
m = AutoPeftModelForCausalLM.from_pretrained("out/friday-hf")
m = m.merge_and_unload()
m.save_pretrained("out/friday-merged")
AutoTokenizer.from_pretrained("out/friday-hf").save_pretrained("out/friday-merged")
# then use out/friday-merged below instead of out/friday-hf
```
*(Skip this if you enabled "merge adapter" in AutoTrain — then the download is already a full model.)*

### Convert HF → GGUF (llama.cpp) and quantize
```bash
git clone https://github.com/ggerganov/llama.cpp
pip install -r llama.cpp/requirements.txt

# HF dir -> full-precision GGUF
python llama.cpp/convert_hf_to_gguf.py out/friday-hf \
    --outfile friday-qwen2.5-3b-f16.gguf --outtype f16

# quantize to q4_k_m (~2 GB, fits an 8 GB CPU box)
# (build llama.cpp first, or use the prebuilt `llama-quantize`)
./llama.cpp/llama-quantize friday-qwen2.5-3b-f16.gguf \
    friday-qwen2.5-3b-q4_k_m.gguf Q4_K_M
```

**Sanity-check it in the cloud before downloading** (optional):
```bash
pip install llama-cpp-python
python -c "from llama_cpp import Llama; \
  m=Llama('friday-qwen2.5-3b-q4_k_m.gguf', n_ctx=4096); \
  print(m('You are Friday. User: who are you? Friday:', max_tokens=60)['choices'][0]['text'])"
```

Then **download `friday-qwen2.5-3b-q4_k_m.gguf`** (only the quantized file, ~2 GB) to this machine.

---

## B. Wire it in locally (deterministic — one command)

```bash
python finetune/wire_local_model.py  /path/to/friday-qwen2.5-3b-q4_k_m.gguf
```

That copies the GGUF into `models/` and sets `friday_config.json` →
`local_brain.enabled = true`, `local_brain.model_file = <name>`. Then:

```bash
pip install llama-cpp-python
python -m core.intelligence.local_reasoner --status          # expect: available = true
python -m core.intelligence.local_reasoner --ask "who are you?"
```

If `--status` shows `available: true` and she answers in her voice, she's
reasoning **locally** — cloud out of the hot path. Done.

---

## Honest notes

- **q4_k_m** is the sweet spot for an 8 GB CPU box (~2 GB resident, good quality).
  If it's tight, `q4_0` is smaller/faster and a bit worse; `q5_k_m` is larger/better.
- The base model download and all training happen **on Hugging Face**, not here — only
  the final ~2 GB GGUF comes home.
- This gives a local Friday **voice + the base model's reasoning**. It is not a
  capability leap over the cloud, and it doesn't add knowledge (that's her
  retrieval). Real capability still needs bigger models / more compute / more data.
