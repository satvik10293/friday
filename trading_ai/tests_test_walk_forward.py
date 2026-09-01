"""
Walk-forward: parameters chosen on in-sample only, scored on unseen out-of-sample.
"""

from __future__ import annotations

from validation import Scorecard
from vision_model.dataset import synth_ohlcv
from walk_forward import default_grid, optimize, walk_forward


def test_grid_is_small_on_purpose():
    g = default_grid()
    assert len(g) == 27                       # 3x3x3 — big grids overfit
    assert all({"entry_score", "stop_atr", "target_atr"} <= set(p) for p in g)


def test_optimize_returns_valid_params():
    df = synth_ohlcv(bars=400, drift=0.4, seed=1)
    p = optimize(df, default_grid())
    assert set(p) == {"entry_score", "stop_atr", "target_atr"}


def test_walk_forward_only_scores_out_of_sample():
    df = synth_ohlcv(bars=800, drift=0.3, vol=1.0, seed=2)
    agg, windows = walk_forward(df, symbol="SYNTH", in_bars=300, out_bars=100)
    assert isinstance(agg, Scorecard)
    assert len(windows) >= 1                   # at least one roll happened
    # each window records the params chosen in-sample and the OOS result
    assert all("params" in w and "oos_trades" in w for w in windows)


def test_short_history_yields_no_windows():
    df = synth_ohlcv(bars=200, drift=0.2, seed=3)   # < in_bars+out_bars
    agg, windows = walk_forward(df, in_bars=300, out_bars=100)
    assert windows == [] and agg.trades == 0
