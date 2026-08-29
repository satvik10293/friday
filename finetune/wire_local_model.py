"""
wire_local_model.py — point FRIDAY's local brain at a fine-tuned GGUF.

Run this on THIS machine AFTER you've converted the fine-tuned model (trained on
Hugging Face) into a .gguf. It copies the file into models/ and updates friday_config.json's
`local_brain` block so LocalReasoner (core/intelligence/local_reasoner.py)
loads it on next boot. Nothing here downloads anything.

    python finetune/wire_local_model.py  /path/to/friday-qwen2.5-3b-q4_k_m.gguf

Then:
    pip install llama-cpp-python
    python -m core.intelligence.local_reasoner --status          # should say available
    python -m core.intelligence.local_reasoner --ask "who are you?"
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
CONFIG = ROOT / "friday_config.json"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python finetune/wire_local_model.py <path-to.gguf>")
        return 2
    src = Path(argv[0]).expanduser()
    if not src.exists() or src.suffix.lower() != ".gguf":
        print(f"not a .gguf file: {src}")
        return 1

    MODELS.mkdir(parents=True, exist_ok=True)
    dest = MODELS / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
        print(f"copied -> {dest.relative_to(ROOT)}")
    else:
        print(f"already in place: {dest.relative_to(ROOT)}")

    cfg: dict = {}
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        except ValueError:
            print(f"warning: {CONFIG.name} was not valid JSON — starting a fresh config block")
            cfg = {}

    lb = dict(cfg.get("local_brain") or {})
    lb["enabled"] = True
    lb["model_file"] = src.name          # LocalReasoner resolves models/<model_file>
    lb.setdefault("n_ctx", 4096)
    lb.setdefault("max_tokens", 700)
    cfg["local_brain"] = lb
    CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    print(f"updated {CONFIG.name}: local_brain.enabled=true, model_file={src.name}")

    print("\nnext:")
    print("  pip install llama-cpp-python")
    print("  python -m core.intelligence.local_reasoner --status")
    print('  python -m core.intelligence.local_reasoner --ask "who are you?"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
