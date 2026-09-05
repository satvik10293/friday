"""
Training pipeline: she learns from history, but is judged out-of-sample. These
pin the honest contract — features are clean, metrics are reported against a
baseline, short data is refused, and a model with NO edge is never saved (so a
no-edge model can never sneak into her decisions).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from train_model import (TrainResult, build_features, save_model,
                         train_and_validate)


def _series(n=400, seed=0, trend=0.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, 0.01, n)
    close = 100 * np.cumprod(1 + rets)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    vol = rng.integers(100_000, 1_000_000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": vol})


def test_features_are_clean_and_labels_binary():
    X, y, fwd, cols = build_features(_series(), horizon=5)
    assert len(X) == len(y) == len(fwd) > 0
    assert np.isfinite(X).all()                       # no NaN/inf leaks into training
    assert set(np.unique(y).tolist()) <= {0, 1}
    assert cols == list(cols)


def test_validate_reports_honest_out_of_sample_metrics():
    res = train_and_validate(_series(n=500, seed=1), horizon=5)
    assert res.ok
    assert 0.0 <= res.oos_accuracy <= 1.0
    assert res.baseline >= 0.5                        # baseline = majority-class guess
    assert isinstance(res.edge, bool)
    assert "sample" in res.verdict().lower()


def test_short_data_is_refused_honestly():
    res = train_and_validate(_series(n=60), horizon=5)
    assert not res.ok
    assert "not enough" in res.reason.lower()


def test_a_model_with_no_edge_is_never_saved(tmp_path):
    no_edge = TrainResult(ok=True, edge=False, model=object(), scaler=object())
    assert save_model(no_edge, path=tmp_path / "m.joblib") is None
    assert not (tmp_path / "m.joblib").exists()       # nothing written
