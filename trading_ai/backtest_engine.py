"""
Phase 6 — Backtesting Engine.

Replays the exact same signal rules (signals_signal_engine.score_bar) over
historical candles, simulating each trade with an ATR-based stop-loss and
target, and reports what actually happened: win rate, average win/loss,
and expectancy per trade.

This is where the risk/profit/loss estimates on live recommendations come
from — measured history, not wishful thinking. If the strategy has been
losing on a symbol, the numbers will say so, and that is the point:
an honest 55% win rate with 1:2 risk:reward makes money over many trades;
a promised "100%" is how accounts get blown up.

Simulation rules (deliberately conservative):
  - Enter long when score >= +entry_score, short when score <= -entry_score
  - Stop = 1.5 x ATR against you, Target = 3.0 x ATR with you (1:2 R:R)
  - One position at a time, entered at the signal bar's close
  - If a bar touches both stop and target, the STOP is assumed to hit first
    (worst case), so results are biased against us, never for us.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from signals_signal_engine import atr, score_bar


@dataclass
class BacktestResult:
    trades: int
    wins: int
    losses: int
    win_rate: float          # 0-1
    avg_win: float           # per share, > 0
    avg_loss: float          # per share, > 0 (magnitude)
    expectancy: float        # per share per trade (win_rate*avg_win - loss_rate*avg_loss)
    note: str = ""

    def __str__(self) -> str:
        if self.trades == 0:
            return "Backtest: no qualifying trades in this history window"
        return (
            f"Backtest: {self.trades} trades, {self.win_rate * 100:.0f}% wins, "
            f"avg win {self.avg_win:+.2f} / avg loss {-self.avg_loss:.2f}, "
            f"expectancy {self.expectancy:+.2f}/share per trade"
            + (f" ({self.note})" if self.note else "")
        )


def run_backtest(
    df: pd.DataFrame,
    entry_score: float = 40.0,
    stop_atr_mult: float = 1.5,
    target_atr_mult: float = 3.0,
) -> BacktestResult:
    """
    df must already contain sma20/sma50/rsi14 columns
    (MarketDataClient.with_indicators). Long and short trades are both
    simulated, mirroring the live engine's BUY and SELL calls.
    """
    atr_series = atr(df)
    pnls: List[float] = []

    direction = 0  # +1 long, -1 short, 0 flat
    entry = stop = target = 0.0

    for i in range(55, len(df)):
        row = df.iloc[i]

        if direction != 0:
            if direction == 1:
                if row.low <= stop:            # stop checked first: worst case
                    pnls.append(stop - entry)
                    direction = 0
                elif row.high >= target:
                    pnls.append(target - entry)
                    direction = 0
            else:
                if row.high >= stop:
                    pnls.append(entry - stop)
                    direction = 0
                elif row.low <= target:
                    pnls.append(entry - target)
                    direction = 0
            continue

        atr_val = atr_series.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        score = score_bar(df, i)
        if score >= entry_score:
            direction, entry = 1, float(row.close)
            stop = entry - stop_atr_mult * float(atr_val)
            target = entry + target_atr_mult * float(atr_val)
        elif score <= -entry_score:
            direction, entry = -1, float(row.close)
            stop = entry + stop_atr_mult * float(atr_val)
            target = entry - target_atr_mult * float(atr_val)

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n = len(pnls)

    if n == 0:
        return BacktestResult(0, 0, 0, 0.0, 0.0, 0.0, 0.0,
                              note="no qualifying setups in window")

    win_rate = len(wins) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

    note = "small sample — low confidence" if n < 10 else ""
    return BacktestResult(n, len(wins), len(losses), win_rate,
                          avg_win, avg_loss, expectancy, note)


# ---- quick manual test -----------------------------------------------------

if __name__ == "__main__":
    from data_market_api import MarketDataClient

    client = MarketDataClient()
    symbol = "RELIANCE.NS"
    candles = client.get_candles(symbol, period="60d", interval="1h")
    df = client.with_indicators(candles)
    result = run_backtest(df)
    print(f"{symbol} — {result}")
