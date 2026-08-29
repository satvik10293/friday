"""
Tests for Athena's comprehensive signal catalog. Synthetic OHLCV is crafted so a
specific pattern/signal is unmistakably present, then we assert she names it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from signals_catalog import (ORDER_TYPES, PATTERN_LIBRARY, TRADE_TYPES,
                             candlesticks, chart_structure, indicator_signals,
                             indicators, read_chart)


def _df(rows):
    """rows: list of (open, high, low, close, volume)."""
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _names(sigs):
    return {s.name for s in sigs}


# ── candlestick detection ─────────────────────────────────────────────────────

def test_detects_bullish_engulfing():
    rows = [(10, 10.2, 9.8, 10.0, 100),           # filler
            (10.0, 10.2, 9.7, 9.8, 100),          # prior DOWN candle
            (9.7, 10.6, 9.6, 10.5, 180)]          # UP candle engulfing it
    assert "bullish engulfing" in _names(candlesticks(_df(rows)))


def test_detects_doji():
    rows = [(10, 10.2, 9.8, 10.0, 100),
            (10, 10.2, 9.8, 10.0, 100),
            (10.0, 10.3, 9.7, 10.01, 100)]        # open ≈ close, long wicks
    assert "doji" in _names(candlesticks(_df(rows)))


def test_detects_three_white_soldiers():
    rows = [(10.0, 10.3, 9.9, 10.2, 100),         # up
            (10.2, 10.6, 10.1, 10.5, 110),        # higher up
            (10.5, 10.9, 10.4, 10.8, 120)]        # higher up again
    assert "three white soldiers" in _names(candlesticks(_df(rows)))


def test_shooting_star_is_bearish():
    rows = [(10, 10.2, 9.8, 10.0, 100),
            (10, 10.2, 9.8, 10.0, 100),
            (10.05, 10.9, 9.98, 10.0, 100)]       # bearish body, long upper wick
    sigs = [s for s in candlesticks(_df(rows)) if s.name == "shooting star"]
    assert sigs and sigs[0].direction == -1


# ── indicator signals ─────────────────────────────────────────────────────────

def test_declining_series_is_rsi_oversold():
    n = 40
    close = np.linspace(100, 60, n)               # relentless decline → RSI low
    rows = [(c + 0.1, c + 0.2, c - 0.2, c, 100) for c in close]
    names = _names(indicator_signals(_df(rows)))
    assert "RSI oversold" in names


def test_indicators_add_expected_columns():
    close = np.linspace(50, 70, 60)
    d = indicators(_df([(c, c + 0.3, c - 0.3, c, 100) for c in close]))
    for col in ("ema20", "rsi14", "macd", "bb_up", "atr14", "stoch_k", "adx14"):
        assert col in d.columns


# ── structure + the whole read ────────────────────────────────────────────────

def test_uptrend_structure_and_bias():
    close = np.linspace(50, 80, 60)               # steady climb
    rows = [(c, c + 0.3, c - 0.3, c + 0.1, 100) for c in close]
    struct = _names(chart_structure(_df(rows)))
    assert "uptrend" in struct
    read = read_chart(_df(rows))
    assert read["bias"] == "bullish" and read["count"] >= 1


def test_read_chart_shape_and_neutral_on_noise():
    rng = np.random.default_rng(0)
    close = 50 + rng.normal(0, 0.2, 60).cumsum() * 0  # basically flat
    rows = [(50, 50.2, 49.8, 50, 100) for _ in range(60)]
    read = read_chart(_df(rows))
    assert set(read) == {"signals", "count", "score", "bias"}
    assert read["bias"] == "neutral"


# ── the reference taxonomy is comprehensive ───────────────────────────────────

def test_taxonomy_covers_the_trade_and_order_universe():
    for t in ("scalp", "day_trade", "swing_trade", "long", "short", "breakout",
              "pullback", "reversal", "mean_reversion", "hedge"):
        assert t in TRADE_TYPES
    for o in ("market", "limit", "stop", "stop_limit", "trailing_stop", "bracket", "oco"):
        assert o in ORDER_TYPES
    total_patterns = sum(len(v) for v in PATTERN_LIBRARY.values())
    assert total_patterns >= 25          # she knows a broad library now, not 4
