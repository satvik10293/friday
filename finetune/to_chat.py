"""
to_chat.py — convert the persona dataset into chat-message format.

The base file finetune/friday_persona.jsonl is Alpaca-style
(instruction / input / output), which LitGPT reads directly. Many
HuggingFace / TRL fine-tuning flows want the chat schema instead:

    {"messages": [
        {"role": "system", "content": "<persona>"},
        {"role": "user", "content": "<instruction (+input)>"},
        {"role": "assistant", "content": "<output>"}
    ]}

This script prepends the persona system prompt and writes that schema to
finetune/friday_persona_chat.jsonl. Pure standard library — no downloads.

    python finetune/to_chat.py
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "friday_persona.jsonl"
DST = HERE / "friday_persona_chat.jsonl"
SYSTEM = (HERE / "friday_system_prompt.txt").read_text(encoding="utf-8").strip()


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
            rec = {"messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
                {"role": "assistant", "content": row["output"]},
            ]}
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} chat-format examples -> {DST.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
