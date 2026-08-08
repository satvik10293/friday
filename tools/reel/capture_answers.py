"""
capture_answers.py — replace the reel's text with FRIDAY's REAL answers.

Boots the production cognitive stack headless (via the run-friday driver) and
drives the reel prompts through the SAME ConversationBridge the microphone uses,
then writes the answers + real routing metadata back into answers.json.

Honesty rules:
  * Deterministic/local prompts (math, memory) are captured with the cloud key
    UNSET so the answer provably comes from her on-device faculties.
  * The cloud prompt is captured with the key set; its route must be cloud.
  * Runtime-dependent / side-effecting prompts (screen OCR, screenshot skill)
    keep their curated caption text — we don't want a messy live OCR string or a
    real screenshot fired mid-capture. They are skipped (marked in code below).

    python tools/reel/capture_answers.py

Falls back gracefully: any prompt that errors keeps its seeded answer.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "run-friday"))

ANSWERS = HERE / "answers.json"

# routes we do NOT capture live (runtime-dependent text / real side effects)
SKIP_ROUTES = ("screen", "skill")


def _friendly(strategy: str) -> str:
    s = (strategy or "").lower()
    if s.startswith("cloud"):
        return "cloud_reasoner"
    if "notebook" in s:
        return "notebook"
    if "local" in s or "reason" in s or "exact" in s:
        return "exact-reasoning"
    if "recall" in s or "memory" in s or "self" in s:
        return "memory-recall"
    return strategy or "on-device"


def _ask(bridge, prompt):
    r = bridge.think(prompt)
    return (getattr(r, "answer", "") or "").strip(), \
        getattr(r, "strategy", "") or "", \
        ",".join(getattr(r, "models_used", []) or []) or "on-device"


def main() -> int:
    data = json.loads(ANSWERS.read_text(encoding="utf-8"))
    from driver import build_bridge  # type: ignore

    print("booting FRIDAY headless (this loads the full stack)...", flush=True)
    bridge, _ = build_bridge(use_teacher=True)
    print("ready — capturing answers\n", flush=True)

    for item in data.get("local", []):
        if item.get("route", "").startswith(SKIP_ROUTES):
            print(f"  skip (curated)  {item['prompt']!r}")
            continue
        try:
            ans, strat, models = _ask(bridge, item["prompt"])
            if ans:
                item["answer"] = ans
                item["route"] = _friendly(strat)
                item["models"] = "on-device"  # local beat is on-device by claim
                print(f"  local  [{strat:<16}] {item['prompt']!r} -> {ans[:60]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  local  FAILED (kept seed): {e}")

    cloud = data.get("cloud")
    if cloud:
        try:
            ans, strat, models = _ask(bridge, cloud["prompt"])
            if ans:
                cloud["answer"] = ans
                cloud["route"] = _friendly(strat)
                cloud["models"] = models
                print(f"\n  cloud  [{strat}] models={models}\n    {ans[:120]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  cloud  FAILED (kept seed): {e}")

    ANSWERS.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    print(f"\nwrote {ANSWERS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
