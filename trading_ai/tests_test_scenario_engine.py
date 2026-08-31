"""
Athena's scenario strategist: enumerate every trade, simulate the outcomes, pick
the maximum-expected-profit plan — fast.
"""

from __future__ import annotations

import numpy as np

from scenario_engine import (best_trade, enumerate_plans, evaluate,
                             simulate_paths, summarize)
from vision_model.dataset import synth_ohlcv


def test_enumerates_both_directions_and_wait():
    plans = enumerate_plans(synth_ohlcv(bars=64, seed=1))
    dirs = {p.direction for p in plans}
    assert "long" in dirs and "short" in dirs and "wait" in dirs
    assert len(plans) >= 10                       # a real search space, not 2 checks


def test_paths_have_the_right_shape_and_realism():
    df = synth_ohlcv(bars=80, drift=0.5, seed=2)
    paths = simulate_paths(df, horizon=24, n=1000, seed=0)
    assert paths.shape == (1000, 24)
    assert (paths > 0).all()                      # prices stay positive


def test_evaluate_returns_a_valid_distribution():
    df = synth_ohlcv(bars=80, drift=0.6, seed=3)
    plans = [p for p in enumerate_plans(df) if p.direction == "long"]
    paths = simulate_paths(df, n=1000, seed=0)
    sc = evaluate(plans[0], paths)
    assert 0.0 <= sc.win_prob <= 1.0
    assert abs(sc.win_prob + sc.loss_prob + sc.timeout_prob - 1.0) < 1e-6


def test_picks_long_in_an_uptrend():
    df = synth_ohlcv(bars=120, drift=0.9, vol=0.8, seed=4)
    strat = best_trade(df, n_paths=3000, seed=0)
    assert strat.action in ("BUY", "WAIT")
    if strat.action == "BUY":
        assert strat.best.plan.direction == "long"
        assert strat.best.ev_per_share > 0


def test_picks_short_in_a_downtrend():
    df = synth_ohlcv(bars=120, drift=-0.9, vol=0.8, seed=5)
    strat = best_trade(df, n_paths=3000, seed=0)
    assert strat.action in ("SELL", "WAIT")
    if strat.action == "SELL":
        assert strat.best.plan.direction == "short"


def test_waits_when_no_edge():
    # a genuinely flat market (~zero drift, tiny vol) → no real edge → WAIT
    import pandas as pd
    osc = 0.05 * np.sin(np.arange(120))
    close = 100.0 + osc
    flat = pd.DataFrame({"open": close, "high": close + 0.05, "low": close - 0.05,
                         "close": close, "volume": [100] * 120})
    strat = best_trade(flat, n_paths=4000, seed=0)
    assert strat.action == "WAIT"


def test_it_is_fast():
    df = synth_ohlcv(bars=120, drift=0.5, seed=7)
    strat = best_trade(df, n_paths=4000, seed=0)
    assert strat.ms < 2000, f"too slow: {strat.ms:.0f} ms"     # well inside 'a few seconds'
    assert strat.n_candidates >= 10


def test_summary_is_human_readable():
    df = synth_ohlcv(bars=120, drift=0.9, seed=8)
    s = summarize(best_trade(df, n_paths=2000, seed=0))
    assert isinstance(s, str) and len(s) > 10
