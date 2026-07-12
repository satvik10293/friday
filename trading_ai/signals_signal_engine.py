"""
Phase 2 — Signal Engine: chart structure analysis from candle data.

Everything here is computed from real OHLCV candles (Eye 1), not from OCR
pixels — candle data is exact, so this is far more reliable than trying to
read the chart image off the screen.

Provides:
  - atr()               Average True Range (volatility — drives stop/target sizing)
  - analyze_chart()     support/resistance levels, candlestick patterns,
                        breakout detection, current ATR
  - score_bar()         the core indicator score for one bar (trend + RSI +
                        volume + momentum). Shared by the live Recommendation
                        Engine and the Backtester so both judge the market by
                        exactly the same rules.

Honesty note: these are probabilistic signals. No chart pattern "perfectly"
predicts the future — the goal is an edge (win more than you lose, and lose
small when wrong), which is why every signal ships with a stop-loss and a
risk:reward estimate instead of a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import pandas as pd


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------

def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range — the standard volatility measure used to place
    stops far enough away that normal noise doesn't shake you out."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


# ---------------------------------------------------------------------------
# Support / resistance
# ---------------------------------------------------------------------------

def find_levels(
    df: pd.DataFrame,
    swing_window: int = 3,
    max_levels: int = 4,
) -> Tuple[List[float], List[float]]:
    """
    Finds horizontal support/resistance levels from swing highs/lows.

    A swing high is a bar whose high is the highest of its neighborhood
    (±swing_window bars); swing lows likewise. Nearby swings are clustered
    into one level (tolerance = 0.3 × ATR) and levels with more touches are
    considered stronger.

    Returns (support, resistance):
      support    — levels below the last close, nearest first
      resistance — levels above the last close, nearest first
    """
    if len(df) < swing_window * 2 + 2:
        return [], []

    w = swing_window
    highs, lows = df["high"], df["low"]

    swings: List[float] = []
    for i in range(w, len(df) - w):
        window_hi = highs.iloc[i - w: i + w + 1]
        window_lo = lows.iloc[i - w: i + w + 1]
        if highs.iloc[i] >= window_hi.max():
            swings.append(float(highs.iloc[i]))
        if lows.iloc[i] <= window_lo.min():
            swings.append(float(lows.iloc[i]))

    if not swings:
        return [], []

    atr_last = atr(df).iloc[-1]
    tol = float(atr_last) * 0.3 if pd.notna(atr_last) and atr_last > 0 else \
        (max(swings) - min(swings)) * 0.01 or 1e-9

    # Cluster nearby swing prices into levels; track touch count as strength
    swings.sort()
    clusters: List[List[float]] = [[swings[0]]]
    for price in swings[1:]:
        if price - clusters[-1][-1] <= tol:
            clusters[-1].append(price)
        else:
            clusters.append([price])

    levels = sorted(
        ((sum(c) / len(c), len(c)) for c in clusters),
        key=lambda lv: lv[1],
        reverse=True,
    )

    last_close = float(df["close"].iloc[-1])
    support = sorted(
        (lv for lv, _ in levels if lv < last_close), reverse=True
    )[:max_levels]
    resistance = sorted(
        lv for lv, _ in levels if lv > last_close
    )[:max_levels]
    return support, resistance


# ---------------------------------------------------------------------------
# Candlestick patterns
# ---------------------------------------------------------------------------

@dataclass
class Pattern:
    name: str
    bias: int  # +1 bullish, -1 bearish


def detect_patterns(df: pd.DataFrame) -> List[Pattern]:
    """Recognizes classic reversal patterns on the last one or two candles."""
    if len(df) < 2:
        return []

    last, prev = df.iloc[-1], df.iloc[-2]
    patterns: List[Pattern] = []

    body = abs(last.close - last.open)
    rng = last.high - last.low
    upper_wick = last.high - max(last.close, last.open)
    lower_wick = min(last.close, last.open) - last.low

    if rng > 0 and body > 0:
        # Hammer: long lower wick, small body near the top -> buyers stepped in
        if lower_wick >= 2 * body and upper_wick <= body:
            patterns.append(Pattern("hammer (buyers rejected lower prices)", +1))
        # Shooting star: long upper wick, small body near the bottom
        elif upper_wick >= 2 * body and lower_wick <= body:
            patterns.append(Pattern("shooting star (sellers rejected higher prices)", -1))

    prev_red = prev.close < prev.open
    prev_green = prev.close > prev.open
    last_green = last.close > last.open
    last_red = last.close < last.open

    # Engulfing: last candle's body completely swallows the previous one's
    if prev_red and last_green and last.close >= prev.open and last.open <= prev.close:
        patterns.append(Pattern("bullish engulfing candle", +1))
    elif prev_green and last_red and last.close <= prev.open and last.open >= prev.close:
        patterns.append(Pattern("bearish engulfing candle", -1))

    return patterns


# ---------------------------------------------------------------------------
# Breakouts
# ---------------------------------------------------------------------------

def detect_breakout(df: pd.DataFrame) -> Optional[str]:
    """
    'up'   — last close crossed above the nearest resistance built from all
             prior bars, on above-average volume
    'down' — last close crossed below the nearest prior support, on volume
    None   — no breakout
    """
    if len(df) < 20:
        return None

    prior = df.iloc[:-1]
    support, resistance = find_levels(prior)
    last, prev = df.iloc[-1], df.iloc[-2]

    avg_vol = df["volume"].iloc[-11:-1].mean()
    volume_ok = bool(avg_vol and last.volume > avg_vol * 1.2)

    # Note: find_levels() splits levels around *prior*'s last close, so after
    # a breakout candle the broken level shows up on the other side of price.
    all_levels = sorted(support + resistance)
    for level in all_levels:
        if prev.close <= level < last.close and volume_ok:
            return "up"
        if prev.close >= level > last.close and volume_ok:
            return "down"
    return None


# ---------------------------------------------------------------------------
# Full chart snapshot
# ---------------------------------------------------------------------------

@dataclass
class ChartAnalysis:
    atr: float
    support: List[float] = field(default_factory=list)      # nearest first
    resistance: List[float] = field(default_factory=list)   # nearest first
    patterns: List[Pattern] = field(default_factory=list)
    breakout: Optional[str] = None

    @property
    def nearest_support(self) -> Optional[float]:
        return self.support[0] if self.support else None

    @property
    def nearest_resistance(self) -> Optional[float]:
        return self.resistance[0] if self.resistance else None


def analyze_chart(df: pd.DataFrame) -> ChartAnalysis:
    """Runs the full structural read of the chart: volatility, levels,
    candlestick patterns, and breakout state."""
    atr_series = atr(df)
    atr_val = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0.0
    support, resistance = find_levels(df)
    return ChartAnalysis(
        atr=atr_val,
        support=support,
        resistance=resistance,
        patterns=detect_patterns(df),
        breakout=detect_breakout(df),
    )


# ---------------------------------------------------------------------------
# Core indicator score — shared by live engine and backtester
# ---------------------------------------------------------------------------

def score_bar(df: pd.DataFrame, i: int) -> float:
    """
    The base trend/momentum score for bar i, using only data available at
    that bar. Positive = bullish, negative = bearish. The live engine adds
    chart-structure points (levels/patterns/breakouts) on top of this; the
    backtester uses it as-is so its statistics stay honest and cheap.
    """
    if i < 1:
        return 0.0
    row, prev = df.iloc[i], df.iloc[i - 1]
    if pd.isna(row.sma20) or pd.isna(row.sma50) or pd.isna(row.rsi14):
        return 0.0

    score = 0.0
    bullish = row.close > row.sma20 > row.sma50
    bearish = row.close < row.sma20 < row.sma50
    if bullish:
        score += 30
    elif bearish:
        score -= 30

    if row.rsi14 < 30:
        score += 20
    elif row.rsi14 > 70:
        score -= 20

    avg_vol = df["volume"].iloc[max(0, i - 10): i].mean()
    if avg_vol and row.volume > avg_vol * 1.3:
        score += 15 if score >= 0 else -15

    if row.close > prev.close and bullish:
        score += 10
    elif row.close < prev.close and bearish:
        score -= 10

    return score
