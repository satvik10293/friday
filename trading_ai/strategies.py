"""
trading_ai/strategies.py — candidate entry strategies for the honest gate.

Each is a signal_fn(df, i) -> score: a positive score above the entry threshold
goes long, below the negative threshold goes short. They plug into
validation.backtest and walk_forward so every idea is judged by the same
un-foolable, cost-aware, out-of-sample test. Adding a strategy here is how we
hunt for an edge — most will fail that test, and that's the point.
"""

from __future__ import annotations

import pandas as pd

from signals_signal_engine import score_bar


def momentum(df: pd.DataFrame, i: int) -> float:
    """The built-in trend/momentum score: SMA trend + RSI + volume. (Tested: no
    out-of-sample edge on liquid US stocks — the baseline.)"""
    return score_bar(df, i)


def mean_reversion(df: pd.DataFrame, i: int) -> float:
    """Fade extremes — buy oversold, sell overbought. The opposite bet from
    momentum. Scaled so the same entry thresholds apply (RSI 30 -> +40 = buy,
    RSI 70 -> -40 = sell)."""
    if i < 20:
        return 0.0
    rsi = df["rsi14"].iloc[i] if "rsi14" in df else None
    if rsi is None or pd.isna(rsi):
        return 0.0
    return (50.0 - float(rsi)) * 2.0


def mr_with_trend_filter(df: pd.DataFrame, i: int) -> float:
    """Mean-reversion, but only WITH the higher trend: buy oversold dips inside an
    uptrend, short overbought pops inside a downtrend (don't fade a strong trend
    head-on). A common 'buy the dip' refinement."""
    if i < 50:
        return 0.0
    row = df.iloc[i]
    rsi = df["rsi14"].iloc[i] if "rsi14" in df else None
    if rsi is None or pd.isna(rsi) or pd.isna(row.get("sma50", float("nan"))):
        return 0.0
    up = row["close"] > row["sma50"]
    if up and rsi < 40:
        return (40.0 - float(rsi)) * 3.0          # buy the dip in an uptrend
    if (not up) and rsi > 60:
        return -(float(rsi) - 60.0) * 3.0         # short the pop in a downtrend
    return 0.0


STRATEGIES = {
    "momentum": momentum,
    "mean_reversion": mean_reversion,
    "mr_trend": mr_with_trend_filter,
}
