"""
dataset.py — build labelled (chart-image, class) training data.

The label for a rendered chart comes from signals_catalog.read_chart() — the rule
engine auto-labels every image, so no manual annotation is needed. A synthetic
OHLCV generator gives unlimited, network-free training data; for a stronger model,
feed real windows from Athena's market API (see build_dataset_from_ohlcv).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from signals_catalog import read_chart

from .render import render_candles

_BIAS_TO_CLASS = {"bearish": 0, "neutral": 1, "bullish": 2}


def label_for(df: pd.DataFrame) -> int:
    """The class Athena's rule engine reads off this window."""
    return _BIAS_TO_CLASS.get(read_chart(df)["bias"], 1)


def synth_ohlcv(bars: int = 64, drift: float = 0.0, vol: float = 1.0,
                seed: int = 0) -> pd.DataFrame:
    """A random-walk OHLCV series with a chosen drift (trend) and volatility."""
    rng = np.random.default_rng(seed)
    close = np.maximum(100 + np.cumsum(rng.normal(drift, vol, bars)), 1.0)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, vol * 0.5, bars))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, vol * 0.5, bars))
    volume = rng.integers(80, 200, bars).astype(float)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume})


def build_synthetic_dataset(n: int = 600, size: int = 64, seed: int = 0):
    """Return (X, y): X is (n, 1, size, size) float32 images, y is (n,) int64."""
    rng = np.random.default_rng(seed)
    X = np.zeros((n, 1, size, size), dtype=np.float32)
    y = np.zeros((n,), dtype=np.int64)
    bars = max(size, 64)
    for i in range(n):
        drift = float(rng.choice([-0.9, -0.5, -0.2, 0.0, 0.2, 0.5, 0.9]))
        df = synth_ohlcv(bars=bars, drift=drift, vol=float(rng.uniform(0.6, 1.4)),
                         seed=int(rng.integers(1_000_000_000)))
        X[i, 0] = render_candles(df, size)
        y[i] = label_for(df)
    return X, y


def build_dataset_from_ohlcv(series, size: int = 64, stride: int = 8):
    """Slide a `size`-bar window across each real OHLCV DataFrame in `series`,
    rendering + auto-labelling each window. Use this with Athena's market API for
    a stronger, real-market training set."""
    xs, ys = [], []
    for df in series:
        if df is None or len(df) < size:
            continue
        for end in range(size, len(df) + 1, stride):
            w = df.iloc[end - size:end]
            xs.append(render_candles(w, size)[None])
            ys.append(label_for(w))
    if not xs:
        return (np.zeros((0, 1, size, size), np.float32), np.zeros((0,), np.int64))
    return np.stack(xs).astype(np.float32), np.asarray(ys, dtype=np.int64)


class ChartDataset:
    """Thin torch Dataset over (X, y) numpy arrays (torch imported lazily)."""

    def __init__(self, X, y) -> None:
        import torch
        self.X = torch.from_numpy(X)
        self.y = torch.from_numpy(y)

    def __len__(self) -> int:
        return len(self.y)

    def __getitem__(self, i):
        return self.X[i], self.y[i]
