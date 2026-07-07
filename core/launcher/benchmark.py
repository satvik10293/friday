"""
core/launcher/benchmark.py — FRIDAY 5.x (M24, Phase B remainder)
The performance truth-teller: measures boot time, per-turn thinking latency,
process RAM and the independence metric from real runs — so Phase H targets
(cold boot < 10 s, simple reply < 700 ms) are tracked from day one instead of
guessed at the end.

    python -m core.launcher.benchmark            # human-readable
    python -m core.launcher.benchmark --json     # machine-readable
"""

from __future__ import annotations

import json
import time


def measure_boot(headless: bool = True) -> dict:
    """One headless startup sequence, timed per stage."""
    from core.launcher.startup import StartupSequence
    t0 = time.perf_counter()
    report = StartupSequence(headless=headless, start_runtime=False).run()
    total_ms = (time.perf_counter() - t0) * 1000.0
    slowest = sorted(report.stages, key=lambda s: s.ms, reverse=True)[:3]
    return {"ready": report.ready, "total_ms": round(total_ms, 1),
            "slowest_stages": [{"stage": s.stage, "ms": round(s.ms, 1)}
                               for s in slowest]}


def measure_turns(prompts: tuple = ("hello friday", "what time is it",
                                    "summarize what you remember about python"),
                  runs: int = 2) -> dict:
    """Per-turn thinking latency through the real local Intelligence OS
    (speech synthesis stubbed out — this measures cognition, not audio)."""
    from core.intelligence.service import IntelligenceOS
    from core.launcher.conversation import ConversationBridge, _SpeechOutput

    class _NullLog:
        def log(self, **row):
            return 0

    ios = IntelligenceOS()
    bridge = ConversationBridge(ios, decision_log=_NullLog(),
                                speech=_SpeechOutput(synthesizer=lambda t: None))
    latencies = []
    for _ in range(runs):
        for prompt in prompts:
            t0 = time.perf_counter()
            bridge.think(prompt)
            latencies.append((time.perf_counter() - t0) * 1000.0)
    latencies.sort()
    return {"turns": len(latencies),
            "p50_ms": round(latencies[len(latencies) // 2], 1),
            "max_ms": round(latencies[-1], 1)}


def measure_memory() -> dict:
    try:
        import psutil
        rss = psutil.Process().memory_info().rss / 1e6
        return {"process_rss_mb": round(rss, 1)}
    except Exception:  # noqa: BLE001
        return {}


def measure_independence() -> dict:
    try:
        from core.observability.decision_log import get_decision_log
        return get_decision_log().independence()
    except Exception:  # noqa: BLE001
        return {}


def run_all() -> dict:
    return {"boot": measure_boot(), "turns": measure_turns(),
            "memory": measure_memory(), "independence": measure_independence(),
            "targets": {"cold_boot_ms": 10_000, "simple_turn_ms": 700}}


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="FRIDAY performance benchmark")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = run_all()
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    boot, turns = report["boot"], report["turns"]
    print(f"boot: {boot['total_ms']:.0f} ms (ready={boot['ready']}) "
          f"target <{report['targets']['cold_boot_ms']} ms")
    for s in boot["slowest_stages"]:
        print(f"  slowest: {s['stage']:<14} {s['ms']:.0f} ms")
    print(f"turns: p50 {turns['p50_ms']:.0f} ms, max {turns['max_ms']:.0f} ms "
          f"target <{report['targets']['simple_turn_ms']} ms")
    if report["memory"]:
        print(f"memory: {report['memory']['process_rss_mb']:.0f} MB RSS")
    ind = report["independence"]
    if ind and ind.get("independence_pct") is not None:
        print(f"independence: {ind['independence_pct']}% local "
              f"({ind['local_turns']}/{ind['total']} turns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
