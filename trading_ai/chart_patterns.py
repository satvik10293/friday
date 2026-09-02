"""
trading_ai/chart_patterns.py — swing-based chart-pattern detection.

Athena's playbook TEACHES head & shoulders, triangles, and flags; this lets her
actually SEE them on price. Detection works off swing highs/lows (local extrema)
and trendline slopes, normalized by ATR so it scales across instruments.

Honest note: chart patterns are the noisiest signals in trading — a detection is
a lean, not a promise. Everything here returns a probabilistic Signal, same as
the rest of the catalog.
"""

from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd

from signals_catalog import BEAR, BULL, NEUTRAL, Signal, _local_extrema, indicators


def _slope(idx: List[int], vals: np.ndarray) -> float:
    if len(idx) < 2:
        return 0.0
    return float(np.polyfit(idx, vals[idx], 1)[0])


def detect_chart_patterns(df: pd.DataFrame, *, lookback: int = 60,
                          w: int = 3) -> List[Signal]:
    """Head & shoulders (±), triangles (asc/desc/symmetrical), and flags."""
    if df is None or len(df) < 40:
        return []
    d = indicators(df)
    c = d["close"].to_numpy(float)
    atr = float(d["atr14"].iloc[-1] or 0.0)
    price = float(c[-1])
    if atr <= 0 or price <= 0:
        return []
    seg = c[-lookback:]
    peaks = _local_extrema(seg, kind="max", w=w)
    troughs = _local_extrema(seg, kind="min", w=w)
    out: List[Signal] = []
    tol = atr * 0.75                                   # "roughly equal" tolerance

    # ── head & shoulders: 3 peaks, middle highest, shoulders similar ──────────
    if len(peaks) >= 3:
        l, m, r = seg[peaks[-3]], seg[peaks[-2]], seg[peaks[-1]]
        if m > l and m > r and abs(l - r) <= tol and (m - max(l, r)) >= tol:
            out.append(Signal("head and shoulders", BEAR, "chart_pattern",
                              "three peaks, a higher head between lower shoulders — reversal", 0.5))
    if len(troughs) >= 3:
        l, m, r = seg[troughs[-3]], seg[troughs[-2]], seg[troughs[-1]]
        if m < l and m < r and abs(l - r) <= tol and (min(l, r) - m) >= tol:
            out.append(Signal("inverse head and shoulders", BULL, "chart_pattern",
                              "three troughs, a lower head between higher shoulders — reversal", 0.5))

    # ── triangles: slope of recent highs vs lows ──────────────────────────────
    if len(peaks) >= 2 and len(troughs) >= 2:
        hi_s = _slope(peaks[-3:], seg) / atr
        lo_s = _slope(troughs[-3:], seg) / atr
        flat = 0.02                                    # near-flat threshold (per bar, ATR units)
        if abs(hi_s) < flat and lo_s > flat:
            out.append(Signal("ascending triangle", BULL, "chart_pattern",
                              "flat highs, rising lows — buyers pressing a ceiling", 0.5))
        elif hi_s < -flat and abs(lo_s) < flat:
            out.append(Signal("descending triangle", BEAR, "chart_pattern",
                              "falling highs, flat lows — sellers pressing a floor", 0.5))
        elif hi_s < -flat and lo_s > flat:
            out.append(Signal("symmetrical triangle", NEUTRAL, "chart_pattern",
                              "converging highs and lows — a coil; trade the break", 0.4))
        elif hi_s > flat and lo_s > flat and lo_s > hi_s:
            out.append(Signal("rising wedge", BEAR, "chart_pattern",
                              "both lines rising but converging — buying is tiring", 0.45))
        elif hi_s < -flat and lo_s < -flat and hi_s < lo_s:
            out.append(Signal("falling wedge", BULL, "chart_pattern",
                              "both lines falling but converging — selling is tiring", 0.45))

    # ── flag / pennant: a strong pole, then a tight counter/quiet consolidation ─
    if len(seg) >= 30:
        pole = seg[-30:-10]
        flag = seg[-10:]
        pole_move = (pole[-1] - pole[0]) / atr
        flag_range = (flag.max() - flag.min()) / atr
        if abs(pole_move) >= 3.0 and flag_range <= 2.0:
            direction = BULL if pole_move > 0 else BEAR
            out.append(Signal("bull flag" if direction > 0 else "bear flag",
                              direction, "chart_pattern",
                              "a sharp move then a tight pause — usually continues", 0.5))
    return out
