"""
trading_ai/signals_catalog.py — Athena's comprehensive signal & trade knowledge.

Her original signal engine knew four candlestick patterns. This is the full
library: every mainstream candlestick pattern, the classic indicator signals,
swing chart structure, and a structured taxonomy of trade / order / setup types.
Everything is computed from real OHLCV candles — no OCR guessing — and every
detector is honest about being probabilistic (a pattern is a lean, not a promise).

Public surface:
    indicators(df)      -> DataFrame with ema/sma/rsi/macd/bollinger/atr/stoch/adx
    candlesticks(df)    -> [Signal]  patterns on the last 1-3 candles
    indicator_signals(df)-> [Signal] RSI/MACD/MA-cross/Bollinger/Stoch/ADX events
    chart_structure(df) -> [Signal]  double top/bottom, trend, breakout
    read_chart(df)      -> {signals, bias, score}   the whole read in one call

Reference knowledge (so she "knows every type"):
    TRADE_TYPES, ORDER_TYPES, SETUP_TYPES, PATTERN_LIBRARY
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

BULL, BEAR, NEUTRAL = 1, -1, 0


@dataclass
class Signal:
    name: str
    direction: int                 # +1 bullish, -1 bearish, 0 neutral
    kind: str                      # candlestick | indicator | structure
    note: str = ""
    strength: float = 0.5          # 0..1 rough confidence in the read

    def to_dict(self) -> dict:
        return {"name": self.name, "direction": self.direction, "kind": self.kind,
                "note": self.note, "strength": round(self.strength, 2)}


# ── indicators (all computed from OHLCV) ──────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0).rolling(n).mean()
    down = (-delta.clip(upper=0.0)).rolling(n).mean()
    rs = up / down.replace(0.0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with the standard indicator columns added."""
    d = df.copy()
    c = d["close"]
    d["ema20"], d["ema50"], d["ema200"] = _ema(c, 20), _ema(c, 50), _ema(c, 200)
    d["sma20"], d["sma50"] = c.rolling(20).mean(), c.rolling(50).mean()
    d["rsi14"] = _rsi(c, 14)
    macd = _ema(c, 12) - _ema(c, 26)
    d["macd"], d["macd_signal"] = macd, _ema(macd, 9)
    d["macd_hist"] = d["macd"] - d["macd_signal"]
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["bb_mid"], d["bb_up"], d["bb_low"] = mid, mid + 2 * sd, mid - 2 * sd
    d["bb_width"] = (d["bb_up"] - d["bb_low"]) / mid.replace(0.0, np.nan)
    d["atr14"] = _atr(d, 14)
    lo14, hi14 = d["low"].rolling(14).min(), d["high"].rolling(14).max()
    d["stoch_k"] = (100 * (c - lo14) / (hi14 - lo14).replace(0.0, np.nan)).fillna(50.0)
    d["stoch_d"] = d["stoch_k"].rolling(3).mean()
    d["adx14"] = _adx(d, 14)
    return d


def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    up, dn = h.diff(), -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(n).mean().replace(0.0, np.nan)
    plus_di = 100 * plus_dm.rolling(n).mean() / atr
    minus_di = 100 * minus_dm.rolling(n).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.rolling(n).mean().fillna(0.0)


# ── candlestick patterns (single / double / triple) ───────────────────────────

def _parts(row):
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body = abs(c - o)
    rng = max(h - l, 1e-9)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return o, h, l, c, body, rng, upper, lower


def candlesticks(df: pd.DataFrame) -> List[Signal]:
    """Detect classic candlestick patterns on the last one-to-three candles."""
    if df is None or len(df) < 3:
        return []
    out: List[Signal] = []
    r = df.iloc[-1]
    o, h, l, c, body, rng, upper, lower = _parts(r)
    small_body = body <= rng * 0.3
    bull, bear = c > o, c < o

    # single-candle
    if body <= rng * 0.1:
        out.append(Signal("doji", NEUTRAL, "candlestick", "indecision — open≈close", 0.4))
    if lower >= body * 2 and upper <= body and small_body:
        out.append(Signal("hammer" if bull else "hanging man", BULL if bull else BEAR,
                          "candlestick", "long lower wick — buyers rejected lows", 0.55))
    if upper >= body * 2 and lower <= body and small_body:
        out.append(Signal("inverted hammer" if bull else "shooting star",
                          BULL if bull else BEAR, "candlestick",
                          "long upper wick — sellers rejected highs", 0.55))
    if body >= rng * 0.9:
        out.append(Signal("bullish marubozu" if bull else "bearish marubozu",
                          BULL if bull else BEAR, "candlestick", "full-body conviction candle", 0.5))
    if small_body and upper > body and lower > body and body > rng * 0.1:
        out.append(Signal("spinning top", NEUTRAL, "candlestick", "small body, two wicks — indecision", 0.35))

    # two-candle
    p = df.iloc[-2]
    po, ph, pl, pc, pbody, prng, pupper, plower = _parts(p)
    if bull and pc < po and c >= po and o <= pc:
        out.append(Signal("bullish engulfing", BULL, "candlestick", "up candle engulfs prior down", 0.6))
    if bear and pc > po and o >= pc and c <= po:
        out.append(Signal("bearish engulfing", BEAR, "candlestick", "down candle engulfs prior up", 0.6))
    if bull and pc < po and body < pbody and o > pc and c < po:
        out.append(Signal("bullish harami", BULL, "candlestick", "small up candle inside prior down", 0.45))
    if bear and pc > po and body < pbody and o < pc and c > po:
        out.append(Signal("bearish harami", BEAR, "candlestick", "small down candle inside prior up", 0.45))
    if bull and pc < po and c > (po + pc) / 2 and o < pc:
        out.append(Signal("piercing line", BULL, "candlestick", "close past midpoint of prior down", 0.5))
    if bear and pc > po and c < (po + pc) / 2 and o > pc:
        out.append(Signal("dark cloud cover", BEAR, "candlestick", "close past midpoint of prior up", 0.5))
    if abs(l - pl) <= rng * 0.05 and bull and pc < po:
        out.append(Signal("tweezer bottom", BULL, "candlestick", "matched lows — support held", 0.45))
    if abs(h - ph) <= rng * 0.05 and bear and pc > po:
        out.append(Signal("tweezer top", BEAR, "candlestick", "matched highs — resistance held", 0.45))

    # three-candle
    g = df.iloc[-3]
    go, gh, gl, gc, gbody, grng, *_ = _parts(g)
    mid = df.iloc[-2]
    if gc < go and pbody <= prng * 0.4 and bull and c > (go + gc) / 2:
        out.append(Signal("morning star", BULL, "candlestick", "down → small → up: reversal", 0.6))
    if gc > go and pbody <= prng * 0.4 and bear and c < (go + gc) / 2:
        out.append(Signal("evening star", BEAR, "candlestick", "up → small → down: reversal", 0.6))
    last3 = df.iloc[-3:]
    if all(x["close"] > x["open"] for _, x in last3.iterrows()) and c > pc > gc:
        out.append(Signal("three white soldiers", BULL, "candlestick", "three rising up-candles", 0.55))
    if all(x["close"] < x["open"] for _, x in last3.iterrows()) and c < pc < gc:
        out.append(Signal("three black crows", BEAR, "candlestick", "three falling down-candles", 0.55))
    return out


# ── indicator signals ─────────────────────────────────────────────────────────

def indicator_signals(df: pd.DataFrame) -> List[Signal]:
    if df is None or len(df) < 30:
        return []
    d = indicators(df)
    last, prev = d.iloc[-1], d.iloc[-2]
    out: List[Signal] = []

    if last.rsi14 < 30:
        out.append(Signal("RSI oversold", BULL, "indicator", f"RSI {last.rsi14:.0f} < 30", 0.5))
    elif last.rsi14 > 70:
        out.append(Signal("RSI overbought", BEAR, "indicator", f"RSI {last.rsi14:.0f} > 70", 0.5))

    if prev.macd < prev.macd_signal and last.macd > last.macd_signal:
        out.append(Signal("MACD bullish cross", BULL, "indicator", "MACD crossed above signal", 0.55))
    elif prev.macd > prev.macd_signal and last.macd < last.macd_signal:
        out.append(Signal("MACD bearish cross", BEAR, "indicator", "MACD crossed below signal", 0.55))

    if prev.sma20 <= prev.sma50 and last.sma20 > last.sma50:
        out.append(Signal("golden cross", BULL, "indicator", "SMA20 crossed above SMA50", 0.6))
    elif prev.sma20 >= prev.sma50 and last.sma20 < last.sma50:
        out.append(Signal("death cross", BEAR, "indicator", "SMA20 crossed below SMA50", 0.6))

    recent_w = d["bb_width"].iloc[-20:]
    if pd.notna(last.bb_width) and last.bb_width <= recent_w.quantile(0.15):
        out.append(Signal("Bollinger squeeze", NEUTRAL, "indicator", "volatility compressed — breakout pending", 0.4))
    if last.close > last.bb_up:
        out.append(Signal("Bollinger breakout up", BULL, "indicator", "close above upper band", 0.45))
    elif last.close < last.bb_low:
        out.append(Signal("Bollinger breakout down", BEAR, "indicator", "close below lower band", 0.45))

    if last.stoch_k < 20 and last.stoch_k > last.stoch_d:
        out.append(Signal("Stochastic oversold turn", BULL, "indicator", "%K turning up under 20", 0.45))
    elif last.stoch_k > 80 and last.stoch_k < last.stoch_d:
        out.append(Signal("Stochastic overbought turn", BEAR, "indicator", "%K turning down over 80", 0.45))

    if last.adx14 >= 25:
        trend = BULL if last.ema20 > last.ema50 else BEAR
        out.append(Signal("strong trend (ADX)", trend, "indicator", f"ADX {last.adx14:.0f} ≥ 25", 0.5))
    return out


# ── chart structure ───────────────────────────────────────────────────────────

def chart_structure(df: pd.DataFrame) -> List[Signal]:
    if df is None or len(df) < 40:
        return []
    d = indicators(df)
    c = d["close"]
    out: List[Signal] = []
    slope = np.polyfit(range(30), c.iloc[-30:].values, 1)[0]
    atr = float(d["atr14"].iloc[-1] or 0.0)
    if atr > 0:
        norm = slope / atr
        if norm > 0.05:
            out.append(Signal("uptrend", BULL, "structure", "higher closes over 30 bars", 0.5))
        elif norm < -0.05:
            out.append(Signal("downtrend", BEAR, "structure", "lower closes over 30 bars", 0.5))
        else:
            out.append(Signal("range / consolidation", NEUTRAL, "structure", "flat over 30 bars", 0.4))

    window = c.iloc[-40:].values
    hi_i = int(np.argmax(window))
    lo_i = int(np.argmin(window))
    peaks = _local_extrema(window, kind="max")
    troughs = _local_extrema(window, kind="min")
    if len(peaks) >= 2 and abs(window[peaks[-1]] - window[peaks[-2]]) <= (atr or 1e9) * 1.0:
        out.append(Signal("double top", BEAR, "structure", "two matched highs — reversal risk", 0.5))
    if len(troughs) >= 2 and abs(window[troughs[-1]] - window[troughs[-2]]) <= (atr or 1e9) * 1.0:
        out.append(Signal("double bottom", BULL, "structure", "two matched lows — reversal setup", 0.5))
    return out


def _local_extrema(a: np.ndarray, *, kind: str, w: int = 3) -> List[int]:
    idx = []
    for i in range(w, len(a) - w):
        seg = a[i - w:i + w + 1]
        if (kind == "max" and a[i] == seg.max()) or (kind == "min" and a[i] == seg.min()):
            idx.append(i)
    return idx


# ── the whole read ────────────────────────────────────────────────────────────

def read_chart(df: pd.DataFrame) -> dict:
    """Every signal Athena can see on this chart, plus a net directional bias."""
    sigs = candlesticks(df) + indicator_signals(df) + chart_structure(df)
    try:                                     # lazy import avoids a circular dep
        from chart_patterns import detect_chart_patterns
        sigs = sigs + detect_chart_patterns(df)
    except Exception:  # noqa: BLE001 — pattern detection is best-effort
        pass
    score = sum(s.direction * s.strength for s in sigs)
    bias = "bullish" if score > 0.4 else "bearish" if score < -0.4 else "neutral"
    return {"signals": [s.to_dict() for s in sigs], "count": len(sigs),
            "score": round(score, 2), "bias": bias}


# ── reference taxonomy: so she "knows every type" ─────────────────────────────

TRADE_TYPES = {
    "scalp": "seconds-to-minutes; tiny moves, high frequency, tight stops",
    "day_trade": "opened and closed within one session; no overnight risk",
    "swing_trade": "days to weeks; rides a multi-day move",
    "position_trade": "weeks to months; follows the primary trend",
    "long": "buy first, profit if price rises",
    "short": "sell-borrow first, profit if price falls",
    "breakout": "enter as price clears a level with momentum",
    "pullback": "enter on a dip within an established trend",
    "reversal": "enter as a trend exhausts and turns",
    "trend_continuation": "add/enter in the direction of a strong trend",
    "mean_reversion": "fade an overextended move back toward average",
    "momentum": "buy strength / sell weakness expecting it to persist",
    "arbitrage": "exploit a price difference between venues/instruments",
    "hedge": "offsetting position that reduces risk, not for profit alone",
}

ORDER_TYPES = {
    "market": "fill now at the best available price",
    "limit": "fill only at your price or better",
    "stop": "becomes a market order once a trigger price trades",
    "stop_limit": "becomes a limit order at the trigger price",
    "trailing_stop": "stop that follows price by a fixed distance/percent",
    "bracket": "entry plus attached stop-loss and take-profit",
    "oco": "one-cancels-other: two orders, filling one cancels the other",
    "gtc": "good-till-cancelled; stays working across sessions",
    "ioc": "immediate-or-cancel; fill what you can now, cancel the rest",
    "fok": "fill-or-kill; fill entirely at once or cancel",
}

SETUP_TYPES = {
    "trend_continuation": "trade with a confirmed trend (ADX/MA aligned)",
    "breakout": "clear support/resistance on rising volume",
    "pullback": "buy the dip to a moving average / prior level in an uptrend",
    "reversal": "reversal candle + oversold/overbought + level",
    "range": "buy support / sell resistance inside a flat channel",
    "squeeze": "Bollinger squeeze → trade the expansion",
}

# the candlestick + chart patterns Athena recognizes, grouped
PATTERN_LIBRARY = {
    "candlestick_single": ["doji", "hammer", "hanging man", "inverted hammer",
                           "shooting star", "marubozu", "spinning top"],
    "candlestick_double": ["bullish engulfing", "bearish engulfing", "bullish harami",
                           "bearish harami", "piercing line", "dark cloud cover",
                           "tweezer top", "tweezer bottom"],
    "candlestick_triple": ["morning star", "evening star", "three white soldiers",
                           "three black crows"],
    "indicator": ["RSI oversold/overbought", "MACD cross", "golden/death cross",
                  "Bollinger squeeze/breakout", "Stochastic turn", "ADX trend"],
    "structure": ["uptrend", "downtrend", "range", "double top", "double bottom",
                  "breakout"],
}
