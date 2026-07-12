"""Offline tests for the multi-timeframe confirmation logic (no network)."""

import numpy as np
import pandas as pd

from recommend_recommendation_engine import (
    Recommendation,
    RecommendationEngine,
    TradePlan,
)


def _htf(trend: str, bars: int = 60) -> pd.DataFrame:
    """Synthetic hourly history whose last bar is clearly in `trend`."""
    if trend == "up":
        close = np.linspace(100, 130, bars)      # rising -> close > sma20 > sma50
    elif trend == "down":
        close = np.linspace(130, 100, bars)
    else:
        close = np.full(bars, 115.0)
    df = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1,
        "close": close, "volume": np.full(bars, 1000),
    })
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["rsi14"] = 50.0
    return df


def _rec(action: str, confidence: float = 60.0) -> Recommendation:
    plan = TradePlan(entry=100.0, stop_loss=95.0, target=110.0,
                     risk_per_share=5.0, reward_per_share=10.0,
                     rr_ratio=2.0, risk_pct=5.0)
    return Recommendation("TEST", action, confidence, ["setup"], plan)


def test_buy_is_vetoed_when_hourly_trend_is_down():
    rec = _rec("BUY")
    RecommendationEngine._apply_higher_timeframe(rec, _htf("down"))
    assert rec.action == "WAIT"
    assert rec.confidence <= 35.0
    assert any("Vetoed BUY" in r for r in rec.reasons)


def test_buy_is_strengthened_when_hourly_trend_agrees():
    rec = _rec("BUY", confidence=60.0)
    RecommendationEngine._apply_higher_timeframe(rec, _htf("up"))
    assert rec.action == "BUY"
    assert rec.confidence == 70.0


def test_sell_is_softened_when_hourly_trend_is_still_up():
    rec = _rec("SELL", confidence=80.0)
    RecommendationEngine._apply_higher_timeframe(rec, _htf("up"))
    assert rec.action == "SELL"          # exit advice is never vetoed
    assert rec.confidence == 50.0
    assert any("may be a dip" in r for r in rec.reasons)


def test_sell_is_strengthened_when_hourly_trend_is_down():
    rec = _rec("SELL", confidence=60.0)
    RecommendationEngine._apply_higher_timeframe(rec, _htf("down"))
    assert rec.confidence == 70.0


def test_flat_hourly_trend_changes_nothing():
    rec = _rec("BUY", confidence=60.0)
    RecommendationEngine._apply_higher_timeframe(rec, _htf("flat"))
    assert rec.action == "BUY"
    assert rec.confidence == 60.0


def test_too_little_history_changes_nothing():
    rec = _rec("BUY", confidence=60.0)
    RecommendationEngine._apply_higher_timeframe(rec, _htf("down", bars=30))
    assert rec.action == "BUY"           # 30 bars: sma50 is NaN, no opinion
