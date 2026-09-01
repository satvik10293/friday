"""
trading_ai/validation.py — the truth test.

Before a single real rupee/dollar is risked, this proves — or disproves —
whether Athena's strategy actually makes money. It replays her REAL signal logic
(score_bar + ATR stops/targets) over historical data, sizes each trade by risk,
and — crucially — subtracts realistic FEES and SLIPPAGE, then reports an honest
scorecard: win rate, expectancy, profit factor, total return, and the worst
drawdown. It ends with a blunt verdict.

Most strategies that look great without costs lose money with them. This exists
so you decide with evidence, not hope. It is NOT financial advice, and a good
backtest is not a promise of future profit — only paper-trading live and then a
tiny real stake you can afford to lose tells the rest.

    python validation.py --symbols AAPL,MSFT,NVDA,RELIANCE.NS --capital 10000
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from signals_signal_engine import atr, score_bar


@dataclass
class Scorecard:
    symbol: str = "portfolio"
    trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0             # $ per winning trade (after costs)
    avg_loss: float = 0.0            # $ per losing trade (after costs, positive number)
    expectancy: float = 0.0         # $ per trade after costs
    profit_factor: float = 0.0      # gross profit / gross loss
    total_return_pct: float = 0.0   # on starting capital
    max_drawdown_pct: float = 0.0
    final_equity: float = 0.0
    starting_capital: float = 0.0
    costs_paid: float = 0.0
    note: str = ""

    @property
    def has_edge(self) -> bool:
        return (self.trades >= 30 and self.expectancy > 0
                and self.profit_factor > 1.0)

    def verdict(self) -> str:
        if self.trades < 30:
            return (f"NOT ENOUGH DATA — only {self.trades} trades. Need ≥30 before "
                    "trusting any number.")
        if self.has_edge:
            return (f"TENTATIVE EDGE — positive expectancy (${self.expectancy:+.2f}/trade) "
                    f"and profit factor {self.profit_factor:.2f} AFTER costs. Paper-trade it "
                    "live next; do NOT risk real money on a backtest alone.")
        return (f"NO PROVEN EDGE — expectancy ${self.expectancy:+.2f}/trade, profit factor "
                f"{self.profit_factor:.2f} after costs. Do NOT trade this with real money.")

    def __str__(self) -> str:
        return (f"[{self.symbol}] {self.trades} trades | {self.win_rate*100:.0f}% win | "
                f"exp ${self.expectancy:+.2f}/trade | PF {self.profit_factor:.2f} | "
                f"return {self.total_return_pct:+.1f}% | maxDD {self.max_drawdown_pct:.1f}% | "
                f"equity ${self.final_equity:,.0f}")


def _ensure_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "sma20" not in d:
        d["sma20"] = d["close"].rolling(20).mean()
    if "sma50" not in d:
        d["sma50"] = d["close"].rolling(50).mean()
    if "rsi14" not in d:
        delta = d["close"].diff()
        up = delta.clip(lower=0).rolling(14).mean()
        dn = (-delta.clip(upper=0)).rolling(14).mean()
        d["rsi14"] = (100 - 100 / (1 + up / dn.replace(0, 1e-9))).fillna(50.0)
    return d


def backtest(df: pd.DataFrame, *, symbol: str = "", capital: float = 10000.0,
             risk_pct: float = 0.01, entry_score: float = 40.0,
             stop_atr: float = 1.5, target_atr: float = 3.0,
             fee_bps: float = 5.0, slippage_bps: float = 5.0,
             signal_fn=None) -> Scorecard:
    """Replay a strategy with position sizing AND costs. `signal_fn(df, i) ->
    score` supplies the entry signal (default: the built-in momentum score_bar);
    a positive score above entry_score goes long, below -entry_score goes short.
    fee+slippage are in basis points per side (5 bps = 0.05%)."""
    sig = signal_fn or score_bar
    d = _ensure_indicators(df)
    atr_s = atr(d)
    cost_rate = (fee_bps + slippage_bps) / 10000.0
    equity = peak = capital
    max_dd = 0.0
    costs_paid = 0.0
    pnls: List[float] = []
    direction = 0
    entry = stop = target = shares = 0.0

    for i in range(55, len(d)):
        row = d.iloc[i]
        if direction != 0:
            exit_price = None
            if direction == 1:
                exit_price = stop if row.low <= stop else (target if row.high >= target else None)
            else:
                exit_price = stop if row.high >= stop else (target if row.low <= target else None)
            if exit_price is not None:
                gross = (exit_price - entry) * shares * direction
                cost = (entry + exit_price) * shares * cost_rate
                pnl = gross - cost
                costs_paid += cost
                equity += pnl
                pnls.append(pnl)
                peak = max(peak, equity)
                if peak > 0:
                    max_dd = max(max_dd, (peak - equity) / peak)
                direction = 0
            continue
        av = atr_s.iloc[i]
        if pd.isna(av) or av <= 0 or equity <= 0:
            continue
        score = sig(d, i)
        if score >= entry_score:
            direction, entry = 1, float(row.close)
            stop, target = entry - stop_atr * av, entry + target_atr * av
        elif score <= -entry_score:
            direction, entry = -1, float(row.close)
            stop, target = entry + stop_atr * av, entry - target_atr * av
        else:
            continue
        rps = abs(entry - stop)
        shares = min((equity * risk_pct) / rps, equity / entry) if rps > 0 and entry > 0 else 0.0

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    n = len(pnls)
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    return Scorecard(
        symbol=symbol or "series", trades=n, wins=len(wins),
        win_rate=len(wins) / n if n else 0.0,
        avg_win=gross_win / len(wins) if wins else 0.0,
        avg_loss=gross_loss / len(losses) if losses else 0.0,
        expectancy=sum(pnls) / n if n else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        total_return_pct=(equity - capital) / capital * 100.0 if capital else 0.0,
        max_drawdown_pct=max_dd * 100.0,
        final_equity=equity, starting_capital=capital, costs_paid=costs_paid,
        note="" if n else "no qualifying setups in window")


def combine(cards: List[Scorecard], capital: float) -> Scorecard:
    """Pool per-symbol results into one honest portfolio scorecard."""
    all_trades = sum(c.trades for c in cards)
    all_wins = sum(c.wins for c in cards)
    total_pnl = sum((c.final_equity - c.starting_capital) for c in cards)
    gross_win = sum(c.avg_win * c.wins for c in cards)
    gross_loss = sum(c.avg_loss * (c.trades - c.wins) for c in cards)
    worst_dd = max((c.max_drawdown_pct for c in cards), default=0.0)
    return Scorecard(
        symbol="PORTFOLIO", trades=all_trades, wins=all_wins,
        win_rate=all_wins / all_trades if all_trades else 0.0,
        avg_win=gross_win / all_wins if all_wins else 0.0,
        avg_loss=gross_loss / (all_trades - all_wins) if (all_trades - all_wins) else 0.0,
        expectancy=total_pnl / all_trades if all_trades else 0.0,
        profit_factor=(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        total_return_pct=total_pnl / capital * 100.0 if capital else 0.0,
        max_drawdown_pct=worst_dd, final_equity=capital + total_pnl,
        starting_capital=capital, costs_paid=sum(c.costs_paid for c in cards))


def validate(symbols: List[str], *, capital: float = 10000.0, period: str = "60d",
             interval: str = "15m", **kw) -> tuple:
    """Backtest each symbol on live history; return (portfolio, per_symbol)."""
    from data_market_api import MarketDataClient, MarketAPIError
    market = MarketDataClient()
    per_symbol: List[Scorecard] = []
    per_capital = capital / max(1, len(symbols))
    for sym in symbols:
        try:
            df = market.get_candles(sym, period=period, interval=interval)
            per_symbol.append(backtest(df, symbol=sym, capital=per_capital, **kw))
        except (MarketAPIError, Exception) as e:  # noqa: BLE001
            per_symbol.append(Scorecard(symbol=sym, note=f"skipped: {e}"))
    return combine([c for c in per_symbol if c.trades], capital), per_symbol


def main(argv=None) -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Prove whether Athena's strategy makes money")
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA,AMZN,GOOGL")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--period", default="60d")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--fee-bps", type=float, default=5.0)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    args = ap.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(f"Backtesting {len(symbols)} symbols on {args.period}/{args.interval} "
          f"with {args.fee_bps+args.slippage_bps:.0f} bps round-trip costs ...\n")
    portfolio, per = validate(symbols, capital=args.capital, period=args.period,
                              interval=args.interval, fee_bps=args.fee_bps,
                              slippage_bps=args.slippage_bps)
    for c in per:
        print("  " + (str(c) if c.trades else f"[{c.symbol}] {c.note}"))
    print("\n" + "=" * 70)
    print("  " + str(portfolio))
    print("=" * 70)
    print("\n  VERDICT: " + portfolio.verdict())
    print("\n  (Not financial advice. A backtest is the floor, not a promise — "
          "paper-trade live before risking money you can afford to lose.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
