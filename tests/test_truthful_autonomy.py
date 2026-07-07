"""
M24 — Truthful autonomy: the independence metric is measured from real
DecisionLog rows (never hardcoded — the 3.0 defect held it at 0%), and the
benchmark module measures real boots and turns.
"""

from __future__ import annotations

from core.launcher import benchmark
from core.observability.decision_log import DecisionLog


def _log(tmp_path):
    return DecisionLog(path=tmp_path / "decisions.db")


def test_independence_is_none_with_no_turns(tmp_path):
    assert _log(tmp_path).independence()["independence_pct"] is None


def test_all_local_turns_measure_100_percent(tmp_path):
    log = _log(tmp_path)
    for _ in range(4):
        log.log(models_used=["friday-reasoner"], route=["direct"], source="voice")
    ind = log.independence()
    assert ind == {"total": 4, "local_turns": 4,
                   "independence_pct": 100.0, "autonomous_pct": 0.0}


def test_external_models_lower_independence_truthfully(tmp_path):
    log = _log(tmp_path)
    log.log(models_used=["friday-reasoner"], route=["direct"])
    log.log(models_used=["cloud:test/model"], route=["direct", "cloud_fallback"])
    ind = log.independence()
    assert ind["total"] == 2 and ind["local_turns"] == 1
    assert ind["independence_pct"] == 50.0


def test_autonomous_share_is_counted(tmp_path):
    log = _log(tmp_path)
    log.log(models_used=[], route=[], was_autonomous=True)
    log.log(models_used=[], route=[], was_autonomous=False)
    assert log.independence()["autonomous_pct"] == 50.0


def test_self_model_surfaces_independence(tmp_path):
    from core.self_model import SelfModel
    log = _log(tmp_path)
    log.log(models_used=["friday-reasoner"], route=["direct"])
    perf = SelfModel(decision_log=log).snapshot()["performance"]
    assert perf["independence_pct"] == 100.0


# ── benchmark ─────────────────────────────────────────────────────────────────

def test_benchmark_measures_a_real_boot_and_real_turns():
    boot = benchmark.measure_boot()
    assert boot["ready"] is True
    assert 0 < boot["total_ms"] < 60_000
    assert len(boot["slowest_stages"]) == 3

    turns = benchmark.measure_turns(prompts=("hello",), runs=1)
    assert turns["turns"] == 1
    assert turns["p50_ms"] > 0


def test_benchmark_report_contains_the_targets():
    report = {"targets": {"cold_boot_ms": 10_000, "simple_turn_ms": 700}}
    full = benchmark.run_all()
    assert full["targets"] == report["targets"]
    assert "boot" in full and "turns" in full
