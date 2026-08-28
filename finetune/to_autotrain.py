"""
to_autotrain.py — package the persona data for Hugging Face AutoTrain (SFT).

AutoTrain's LLM fine-tuner (SFT) trains on a single `text` column: each row is
one full example, already rendered with the chat template. This script renders
every persona example into Qwen's native ChatML template (we recommend the
Qwen2.5-3B base, which matches core/intelligence/local_reasoner.py) and writes:

    finetune/friday_autotrain.jsonl   — one {"text": "..."} per line

In the AutoTrain UI: LLM SFT task, upload this file, set the text column to
`text`, pick your base model. Std-lib only; no downloads.

    python finetune/to_autotrain.py

If you fine-tune a NON-Qwen base, don't use this file — feed the chat file
(friday_persona_chat.jsonl) and let AutoTrain apply that model's own template.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "friday_persona.jsonl"
DST = HERE / "friday_autotrain.jsonl"
SYSTEM = (HERE / "friday_system_prompt.txt").read_text(encoding="utf-8").strip()


def chatml(system: str, user: str, assistant: str) -> str:
    return (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n"
            f"<|im_start|>assistant\n{assistant}<|im_end|>")


def main() -> None:
    n = 0
    with SRC.open(encoding="utf-8") as fin, DST.open("w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            user = row["instruction"]
            if row.get("input"):
                user = f"{user}\n\n{row['input']}"
            text = chatml(SYSTEM, user, row["output"])
            fout.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} AutoTrain rows -> {DST.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
