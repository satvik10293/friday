"""
tools/harness_smoke.py — live end-to-end smoke test for the harness council.

Runs one real question through the cloud council — every AI subscription whose
API key is present in .env answers in parallel and one best answer is
synthesized. This makes REAL API calls (spends a little credit), so it is a
manual diagnostic, never part of the test suite.

Usage:
    python tools/harness_smoke.py                      # default reasoning trap
    python tools/harness_smoke.py "your question here"
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.harness import (Capability, HarnessOrchestrator,  # noqa: E402
                          build_registry, configured_vendors)

_DEFAULT_Q = ("A bat and a ball cost $1.10 in total. The bat costs $1.00 more "
              "than the ball. How much does the ball cost? Explain briefly.")


def main() -> int:
    question = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_Q
    print("configured vendors:", configured_vendors())

    reg = build_registry(include_local=False, only_available=True)
    providers = [p.info.name for p in reg.all()]
    print("cloud providers  :", providers)
    if not providers:
        print("No cloud API keys in .env — nothing to smoke. Add a key and retry.")
        return 1

    orch = HarnessOrchestrator(reg)
    # council directly so every candidate is visible; run_auto would pick council
    # for this (hard) question anyway.
    task = asyncio.run(orch.council(question, capability=Capability.REASONING))

    meta = (task.result.meta if task.result else {}) or {}
    print("\nQUESTION :", question)
    print("state    :", task.state.value)
    print("council  :", meta.get("council"))
    print("synth by :", task.provider, "| synthesized:", meta.get("synthesized"))

    for name, text in (meta.get("candidates") or {}).items():
        print(f"\n--- candidate: {name} ---\n{text}")

    print("\n=== FINAL (synthesized) ===")
    print(task.result.text if task.result else "(no answer)")
    return 0 if task.succeeded else 2


if __name__ == "__main__":
    raise SystemExit(main())
