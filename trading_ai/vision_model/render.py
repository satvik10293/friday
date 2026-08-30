"""
render.py — turn an OHLCV window into a grayscale chart image (pure numpy).

One candle per column, price scaled to rows (row 0 = top = highest price).
Direction is encoded by intensity so a 1-channel image still carries it:

    up-candle body   = 1.0     down-candle body = 0.65     wick = 0.3

Deterministic and dependency-light (numpy only) so it runs the same in training,
tests, and live inference. Live screenshots go through a separate path (resize +
grayscale); this renderer is for building the training set from OHLCV.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BODY_UP, BODY_DOWN, WICK = 1.0, 0.65, 0.3


def render_candles(df: pd.DataFrame, size: int = 64) -> np.ndarray:
    """Render the last `size` candles into a (size, size) float32 image in [0,1]."""
    canvas = np.zeros((size, size), dtype=np.float32)
    if df is None or len(df) == 0:
        return canvas
    d = df.iloc[-size:]
    o = d["open"].to_numpy(float)
    h = d["high"].to_numpy(float)
    l = d["low"].to_numpy(float)
    c = d["close"].to_numpy(float)
    lo, hi = float(np.min(l)), float(np.max(h))
    span = hi - lo
    if span <= 0:
        return canvas
    n = len(d)
    x0 = size - n                                  # right-align if fewer than `size`

    def row(price: float) -> int:
        # highest price -> row 0 (top); clamp into range
        r = int(round((hi - price) / span * (size - 1)))
        return min(size - 1, max(0, r))

    for i in range(n):
        x = x0 + i
        hy, ly = row(h[i]), row(l[i])
        canvas[hy:ly + 1, x] = np.maximum(canvas[hy:ly + 1, x], WICK)   # wick
        oy, cy = row(o[i]), row(c[i])
        top, bot = min(oy, cy), max(oy, cy)
        canvas[top:bot + 1, x] = BODY_UP if c[i] >= o[i] else BODY_DOWN  # body
    return canvas


def image_from_array(arr: np.ndarray, size: int = 64) -> np.ndarray:
    """Normalise an arbitrary grayscale array (e.g. a screenshot crop) to a
    (size, size) float32 image in [0,1] for live inference. Nearest-neighbour
    resize keeps it dependency-free."""
    a = np.asarray(arr, dtype=np.float32)
    if a.ndim == 3:                                # collapse channels to gray
        a = a.mean(axis=2)
    if a.max() > 1.0:
        a = a / 255.0
    h, w = a.shape
    ys = (np.linspace(0, h - 1, size)).astype(int)
    xs = (np.linspace(0, w - 1, size)).astype(int)
    return a[np.ix_(ys, xs)].astype(np.float32)
