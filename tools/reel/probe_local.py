"""
probe_local.py — find prompts that GENUINELY answer on-device (cloud disabled).

Builds a fully-local bridge (build_bridge(use_teacher=False): no cloud reasoner,
no teacher) and prints the route + answer for a set of candidate prompts, so we
only put honestly-local beats in the reel. Nothing is written.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "run-friday"))

CANDIDATES = [
    "How many minutes are in 3 and a half hours?",
    "What is 15% of 240?",
    "What is 25 times 8?",
    "What is the square root of 144?",
    "Convert 5 kilometers to miles.",
    "All engineers solve problems. Sam is an engineer. Does Sam solve problems?",
    "If all birds can fly and a robin is a bird, can a robin fly?",
    "Is 97 a prime number?",
    "What is 144 divided by 12?",
    "Sort these numbers: 8, 3, 15, 1, 9.",
]


def main() -> int:
    from driver import build_bridge  # type: ignore
    print("booting FRIDAY headless, CLOUD DISABLED (local-only)...", flush=True)
    bridge, _ = build_bridge(use_teacher=False)
    # belt-and-suspenders: ensure no cloud path is reachable
    bridge.reasoner = None
    bridge.teacher = None
    print("ready — probing local faculties\n", flush=True)
    for p in CANDIDATES:
        try:
            r = bridge.think(p)
            strat = getattr(r, "strategy", "?")
            conf = float(getattr(r, "confidence", 0.0) or 0.0)
            ans = (getattr(r, "answer", "") or "").strip().replace("\n", " ")
            print(f"[{strat:<16} {conf:.2f}] {p}\n    -> {ans[:110]}\n")
        except Exception as e:  # noqa: BLE001
            print(f"[FAILED] {p}: {e}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
