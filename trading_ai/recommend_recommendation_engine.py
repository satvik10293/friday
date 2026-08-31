"""
Phase 3 — Recommendation Engine (chart-aware).

Combines three inputs into one call — BUY / SELL / HOLD / WAIT:

  1. Indicator score (signals_signal_engine.score_bar):
     trend (SMA20/50), momentum (RSI), volume, candle momentum.
  2. Chart structure (signals_signal_engine.analyze_chart):
     support/resistance levels, candlestick patterns (hammer, engulfing,
     shooting star), volume-confirmed breakouts, ATR volatility.
  3. History: strategy_scores from the learning DB, plus a backtest of the
     same rules over ~60 days of hourly candles to measure the real win
     rate and expectancy for this symbol.

Every BUY/SELL ships with a TradePlan: entry, ATR/level-based stop-loss,
target, risk and reward per share, risk:reward ratio, and the
backtest-estimated win probability and expected profit per trade.

Honesty by design: markets cannot be predicted "perfectly, every time" —
anyone claiming that is lying. The edge here is probabilistic: take setups
where history says you win more than you lose, always know your exit
before you enter, and keep losses small. The numbers shown are measured
from data, not invented.

- "WAIT" is distinct from "HOLD": HOLD means "you have a position, stay
  in it"; WAIT means "no position, no clear setup, don't enter."
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from backtest_engine import BacktestResult, run_backtest
from data_db import Database
from data_market_api import MarketAPIError, MarketDataClient
from signals_signal_engine import ChartAnalysis, analyze_chart, score_bar

# How long a symbol's backtest stats stay cached (it's a slow network fetch
# and history barely changes intraday).
_BACKTEST_TTL_SECONDS = 30 * 60


@dataclass
class TradePlan:
    entry: float
    stop_loss: float
    target: float
    risk_per_share: float
    reward_per_share: float
    rr_ratio: float                    # reward / risk
    risk_pct: float                    # risk as % of entry price
    est_win_rate: Optional[float] = None        # 0-1, from backtest
    expected_pnl_per_share: Optional[float] = None
    backtest_trades: Optional[int] = None
    backtest_note: str = ""

    def __str__(self) -> str:
        lines = [
            f"Entry {self.entry:.2f} | Stop-loss {self.stop_loss:.2f} | Target {self.target:.2f}",
            f"Risk {self.risk_per_share:.2f}/share ({self.risk_pct:.2f}%) | "
            f"Reward {self.reward_per_share:.2f}/share | R:R 1:{self.rr_ratio:.1f}",
        ]
        if self.est_win_rate is not None:
            note = f" — {self.backtest_note}" if self.backtest_note else ""
            lines.append(
                f"Backtest ({self.backtest_trades} past trades): "
                f"{self.est_win_rate * 100:.0f}% win rate, "
                f"expected {self.expected_pnl_per_share:+.2f}/share per trade{note}"
            )
        return "\n".join(lines)


@dataclass
class Recommendation:
    symbol: str
    action: str  # BUY, SELL, HOLD, WAIT
    confidence: float  # 0-100
    reasons: List[str] = field(default_factory=list)
    plan: Optional[TradePlan] = None

    def __str__(self) -> str:
        lines = [f"{self.action} SIGNAL — {self.symbol}", f"Confidence: {self.confidence:.0f}%"]
        if self.plan is not None:
            lines.append(str(self.plan))
        for r in self.reasons:
            lines.append(f"  - {r}")
        return "\n".join(lines)


class RecommendationEngine:
    def __init__(self, market: Optional[MarketDataClient] = None, db: Optional[Database] = None):
        self.market = market or MarketDataClient()
        self.db = db or Database()
        self._backtest_cache: Dict[str, Tuple[float, BacktestResult]] = {}
        self._history_cache: Dict[str, Tuple[float, pd.DataFrame]] = {}

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def evaluate(
        self, symbol: str, has_open_position: bool = False, setup_tag: str = "trend_continuation"
    ) -> Recommendation:
        try:
            candles = self.market.get_candles(symbol, period="5d", interval="15m")
        except MarketAPIError as exc:
            return Recommendation(symbol, "WAIT", 0.0, [f"Could not fetch data: {exc}"])

        df = self.market.with_indicators(candles)
        rec = self._evaluate_from_indicators(df, symbol, has_open_position, setup_tag)

        # Multi-timeframe confirmation: a 15m signal that fights the 1-hour
        # trend is much more likely to fail. Veto buys against the tide;
        # strengthen calls the higher timeframe agrees with.
        htf = self._get_history(symbol)
        if htf is not None:
            self._apply_higher_timeframe(rec, htf)

        # Rule zero of risk management: never risk more than you stand to
        # make. If the nearest level chokes the target, skip the trade.
        if rec.plan is not None and rec.action == "BUY" and rec.plan.rr_ratio < 1.0:
            rec.action = "WAIT"
            rec.confidence = min(rec.confidence, 35.0)
            rec.reasons.append(
                f"Skipped BUY: risk:reward is 1:{rec.plan.rr_ratio:.1f} — "
                "you'd risk more than you could win before the next resistance"
            )

        # Attach measured history to actionable calls
        if rec.plan is not None:
            self._attach_backtest_stats(symbol, rec.plan)
            expected = rec.plan.expected_pnl_per_share
            if expected is not None and expected < 0:
                rec.confidence = min(rec.confidence, 35.0)
                rec.reasons.append(
                    "WARNING: this strategy has been LOSING on this symbol recently "
                    f"(backtest expectancy {expected:+.2f}/share)"
                )
                # A buy signal with measured negative expectancy is not a buy.
                # (SELL is left intact — it doubles as "get out" advice.)
                if rec.action == "BUY" and (rec.plan.backtest_trades or 0) >= 10:
                    rec.action = "WAIT"
                    rec.reasons.append("Downgraded BUY -> WAIT: history says this setup isn't paying here")

        self._enrich(rec, df)
        return rec

    # ------------------------------------------------------------------
    # Expert read: comprehensive catalog + playbook + chart-vision model
    # ------------------------------------------------------------------

    def _enrich(self, rec: "Recommendation", df) -> None:
        """Attach the full expert read to the recommendation's reasons — every
        signal the catalog detects, WITH why-it-happens and entry/target/stop
        from the playbook, plus the trained chart-vision model's take. Additive
        only: it never changes the action/confidence, and never raises (a stumble
        here must not break a live recommendation)."""
        try:
            from trading_knowledge import explain_chart
            read = explain_chart(df)
        except Exception:  # noqa: BLE001
            return
        rec.reasons.append(
            f"— Expert read: {read['bias'].upper()} bias, {read['count']} signals")
        for s in read["signals"][:6]:
            if s.get("why"):
                rec.reasons.append(f"  • {s['name']}: {s['why']}")
            if s.get("entry") or s.get("stop_loss"):
                rec.reasons.append(
                    f"    → enter: {s.get('entry', '-')}  |  stop: {s.get('stop_loss', '-')}")

        # a trading-side discipline reminder, matched to the situation
        try:
            from trading_knowledge import explain
            names = " ".join(sig["name"].lower() for sig in read["signals"])
            if read["bias"] == "neutral" or rec.action == "WAIT":
                topic = "when not to trade"                # no clear edge → patience
            elif "overbought" in names or "shooting star" in names:
                topic = "FOMO"                             # extended → don't chase
            elif rec.action == "BUY":
                topic = "risk per trade"                   # sizing/risk first
            else:
                topic = "cutting losers fast"
            lesson = explain(topic)
            if lesson is not None:
                rec.reasons.append(
                    f"— Discipline: {lesson.name} — {lesson.apply or lesson.why}")
        except Exception:  # noqa: BLE001
            pass

        try:
            from vision_model.predict import ChartPredictor
            predictor = ChartPredictor("out/chartnet.pt")
            if predictor.available():
                v = predictor.predict_df(df)
                rec.reasons.append(
                    f"— Chart-vision model sees {v['class'].upper()} "
                    f"(confidence {v['confidence']})")
        except Exception:  # noqa: BLE001 — vision model is optional
            pass

        # strategist: simulate every candidate trade's outcomes, surface the
        # maximum-expected-profit plan (fast Monte Carlo; never changes the action)
        try:
            from scenario_engine import best_trade, summarize
            rec.reasons.append(f"— Strategist: {summarize(best_trade(df))}")
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Multi-timeframe confirmation
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_higher_timeframe(rec: Recommendation, htf: pd.DataFrame) -> None:
        """Adjusts a 15m-based call using the 1-hour trend (in place)."""
        if len(htf) < 50 or htf[["sma20", "sma50"]].iloc[-1].isna().any():
            return
        last = htf.iloc[-1]
        htf_bull = last.close > last.sma20 > last.sma50
        htf_bear = last.close < last.sma20 < last.sma50

        if rec.action == "BUY":
            if htf_bear:
                rec.action = "WAIT"
                rec.confidence = min(rec.confidence, 35.0)
                rec.reasons.append(
                    "Vetoed BUY: the 1-hour timeframe is in a DOWNTREND — "
                    "buying against the bigger tide loses more often than it wins"
                )
            elif htf_bull:
                rec.confidence = min(100.0, rec.confidence + 10)
                rec.reasons.append("1-hour trend agrees (uptrend) — signal strengthened")
        elif rec.action == "SELL":
            if htf_bull:
                rec.confidence = min(rec.confidence, 50.0)
                rec.reasons.append(
                    "Caution: the 1-hour timeframe is still in an UPTREND — "
                    "this may be a dip, not a reversal"
                )
            elif htf_bear:
                rec.confidence = min(100.0, rec.confidence + 10)
                rec.reasons.append("1-hour trend agrees (downtrend) — signal strengthened")

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _evaluate_from_indicators(
        self, df: pd.DataFrame, symbol: str, has_open_position: bool, setup_tag: str
    ) -> Recommendation:
        if len(df) < 50 or df[["sma20", "sma50", "rsi14"]].iloc[-1].isna().any():
            return Recommendation(symbol, "WAIT", 0.0, ["Not enough history yet for reliable indicators"])

        last = df.iloc[-1]
        reasons: List[str] = []

        # --- 1) core indicator score (shared with the backtester) ---------
        score = score_bar(df, len(df) - 1)

        bullish_trend = last.close > last.sma20 > last.sma50
        bearish_trend = last.close < last.sma20 < last.sma50
        if bullish_trend:
            reasons.append("Uptrend confirmed (price > SMA20 > SMA50)")
        elif bearish_trend:
            reasons.append("Downtrend confirmed (price < SMA20 < SMA50)")
        if last.rsi14 < 30:
            reasons.append(f"RSI oversold ({last.rsi14:.1f}) — potential bounce")
        elif last.rsi14 > 70:
            reasons.append(f"RSI overbought ({last.rsi14:.1f}) — potential pullback")
        recent_avg_vol = df["volume"].iloc[-11:-1].mean()
        if recent_avg_vol and last.volume > recent_avg_vol * 1.3:
            reasons.append("Volume increasing vs recent average")

        # --- 2) chart structure: levels, patterns, breakouts ---------------
        chart = analyze_chart(df)

        for pattern in chart.patterns:
            score += 15 * pattern.bias
            reasons.append(f"Candlestick: {pattern.name}")

        if chart.breakout == "up":
            score += 20
            reasons.append("Breakout ABOVE resistance on rising volume")
        elif chart.breakout == "down":
            score -= 20
            reasons.append("Breakdown BELOW support on rising volume")

        if chart.atr > 0:
            near = 0.5 * chart.atr
            sup, res = chart.nearest_support, chart.nearest_resistance
            if score > 0 and sup is not None and (last.close - sup) <= near:
                score += 10
                reasons.append(f"Price sitting on support at {sup:.2f}")
            if score > 0 and res is not None and (res - last.close) <= near:
                score -= 10
                reasons.append(f"Caution: resistance just overhead at {res:.2f}")
            if score < 0 and res is not None and (res - last.close) <= near:
                score -= 10
                reasons.append(f"Price rejected at resistance {res:.2f}")
            if score < 0 and sup is not None and (last.close - sup) <= near:
                score += 10
                reasons.append(f"Caution: support just below at {sup:.2f}")

        # --- 3) learning history nudges the score --------------------------
        history = self.db.get_strategy_score(setup_tag)
        if history and (history["wins"] + history["losses"]) >= 5:
            win_rate = history["confidence"]
            total = history["wins"] + history["losses"]
            reasons.append(
                f"Similar '{setup_tag}' setup won {history['wins']} of last {total} times"
            )
            score *= 0.5 + win_rate  # win_rate 0 -> halves score, 1 -> 1.5x score

        # --- decision -------------------------------------------------------
        confidence = min(100.0, abs(score))
        plan: Optional[TradePlan] = None

        if score >= 40:
            action = "HOLD" if has_open_position else "BUY"
            plan = self._build_plan(last, chart, direction=+1)
        elif score <= -40:
            action = "SELL"
            plan = self._build_plan(last, chart, direction=-1)
            if not has_open_position:
                reasons.append("No open position — SELL means: exit if you hold this, don't buy now")
        else:
            action = "HOLD" if has_open_position else "WAIT"
            if not reasons:
                reasons.append("No clear setup — indicators are mixed or flat")

        return Recommendation(symbol, action, confidence, reasons, plan)

    # ------------------------------------------------------------------
    # Trade plan: entry / stop / target / risk / reward
    # ------------------------------------------------------------------

    @staticmethod
    def _build_plan(last: pd.Series, chart: ChartAnalysis, direction: int) -> Optional[TradePlan]:
        """ATR-based stop and 1:2 target, tightened to chart levels when a
        level sits closer than the pure-ATR placement."""
        if chart.atr <= 0:
            return None

        entry = float(last.close)
        atr_val = chart.atr

        if direction > 0:  # BUY
            stop = entry - 1.5 * atr_val
            sup = chart.nearest_support
            # A stop just below real support is structurally safer than a
            # pure volatility stop — use it when support is close enough.
            if sup is not None and stop < sup < entry:
                stop = sup - 0.25 * atr_val
            target = entry + 2.0 * (entry - stop)
            res = chart.nearest_resistance
            if res is not None and entry < res < target:
                target = res  # don't plan profits through a wall of sellers
        else:  # SELL / short
            stop = entry + 1.5 * atr_val
            res = chart.nearest_resistance
            if res is not None and entry < res < stop:
                stop = res + 0.25 * atr_val
            target = entry - 2.0 * (stop - entry)
            sup = chart.nearest_support
            if sup is not None and target < sup < entry:
                target = sup

        risk = abs(entry - stop)
        reward = abs(target - entry)
        if risk <= 0:
            return None

        return TradePlan(
            entry=entry,
            stop_loss=stop,
            target=target,
            risk_per_share=risk,
            reward_per_share=reward,
            rr_ratio=reward / risk,
            risk_pct=risk / entry * 100,
        )

    # ------------------------------------------------------------------
    # Backtest-derived probability / expectancy
    # ------------------------------------------------------------------

    def _attach_backtest_stats(self, symbol: str, plan: TradePlan) -> None:
        result = self._get_backtest(symbol)
        if result is None or result.trades == 0:
            plan.backtest_note = "no backtest history available"
            return

        plan.est_win_rate = result.win_rate
        plan.backtest_trades = result.trades
        plan.backtest_note = result.note
        # Expected P&L for THIS plan's risk/reward at the measured win rate
        plan.expected_pnl_per_share = (
            result.win_rate * plan.reward_per_share
            - (1 - result.win_rate) * plan.risk_per_share
        )

    def _get_history(self, symbol: str) -> Optional[pd.DataFrame]:
        """~60 days of hourly candles with indicators, cached. Shared by the
        backtester and the multi-timeframe check — one download serves both."""
        cached = self._history_cache.get(symbol)
        if cached is not None and (time.time() - cached[0]) < _BACKTEST_TTL_SECONDS:
            return cached[1]

        try:
            candles = self.market.get_candles(symbol, period="60d", interval="1h")
            df = self.market.with_indicators(candles)
        except Exception as exc:  # history is best-effort, never blocks a signal
            print(f"[History] hourly fetch skipped for {symbol}: {exc}")
            return None

        self._history_cache[symbol] = (time.time(), df)
        return df

    def _get_backtest(self, symbol: str) -> Optional[BacktestResult]:
        cached = self._backtest_cache.get(symbol)
        if cached is not None and (time.time() - cached[0]) < _BACKTEST_TTL_SECONDS:
            return cached[1]

        df = self._get_history(symbol)
        if df is None:
            return None
        result = run_backtest(df)
        self._backtest_cache[symbol] = (time.time(), result)
        return result
