"""
Chart-pattern detection — she now SEES what her playbook teaches. Synthetic price
is shaped into each pattern, then we assert she names it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from chart_patterns import detect_chart_patterns
from signals_catalog import read_chart


def _df(close):
    close = np.asarray(close, float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + 0.1
    low = np.minimum(open_, close) - 0.1
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": [100] * len(close)})


def _names(sigs):
    return {s.name for s in sigs}


def _head_and_shoulders():
    segs = [np.full(10, 100.0),                                   # lead-in (>=40 bars total)
            np.linspace(100, 105, 8), np.linspace(105, 100, 6)[1:],
            np.linspace(100, 112, 8)[1:], np.linspace(112, 100, 6)[1:],
            np.linspace(100, 105, 8)[1:], np.linspace(105, 98, 6)[1:]]
    return np.concatenate(segs)


def _ascending_triangle():
    close = []
    for lo in np.linspace(100, 108, 6):
        close += list(np.linspace(lo, 110, 5)) + list(np.linspace(110, lo, 5))[1:]
    return np.array(close)


def _bull_flag():
    return np.concatenate([np.full(30, 100.0), np.linspace(100, 120, 20),
                           120 + 0.3 * np.sin(np.arange(10))])


def test_detects_head_and_shoulders():
    assert "head and shoulders" in _names(detect_chart_patterns(_df(_head_and_shoulders())))


def test_detects_ascending_triangle():
    assert "ascending triangle" in _names(detect_chart_patterns(_df(_ascending_triangle())))


def test_detects_bull_flag():
    assert "bull flag" in _names(detect_chart_patterns(_df(_bull_flag())))


def test_no_crash_on_short_or_flat():
    assert detect_chart_patterns(_df(np.full(20, 100.0))) == []          # too short
    assert isinstance(detect_chart_patterns(_df(np.full(60, 100.0))), list)  # flat, no crash


def test_read_chart_now_includes_chart_patterns():
    read = read_chart(_df(_head_and_shoulders()))
    kinds = {s["kind"] for s in read["signals"]}
    assert "chart_pattern" in kinds


def _rising_wedge():
    # highs rise slowly, lows rise faster → the range converges upward (bearish)
    close = []
    for k, (lo, hi) in enumerate(zip(np.linspace(100, 116, 7), np.linspace(110, 118, 7))):
        close += list(np.linspace(lo, hi, 5)) + list(np.linspace(hi, lo, 5))[1:]
    return np.array(close)


def test_detects_rising_wedge():
    assert "rising wedge" in _names(detect_chart_patterns(_df(_rising_wedge())))
