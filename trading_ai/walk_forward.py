"""
trading_ai/walk_forward.py — the un-foolable edge test.

The trap in trading is overfitting: tune a strategy until the backtest looks
great on the past, then watch it lose on live data it never saw. Walk-forward
testing defeats that. It rolls through history:

    [--- optimize params on IN-SAMPLE ---][test on OUT-OF-SAMPLE]  →  slide  →  ...

Parameters are chosen ONLY on in-sample data; performance is scored ONLY on the
next, unseen out-of-sample slice. The aggregate out-of-sample scorecard is the
honest estimate of the edge — because the strategy never saw that data when it
was tuned. If the out-of-sample result is a loser, the "edge" was an illusion.

    python walk_forward.py --symbols AAPL,MSFT,NVDA --period 60d --interval 15m

Not financial advice. Even a clean walk-forward is evidence, not a guarantee —
paper-trade it live before risking money you can afford to lose.
"""

from __future__ import annotations

import argparse
from itertools import product
from typing import List, Optional, Tuple

import pandas as pd

from validation import Scorecard, backtest, combine


def default_grid() -> List[dict]:
    """The parameter space we let the strategy pick from — kept small on purpose
    (a huge grid is itself a form of overfitting)."""
    grid = []
    for es, sa, ta in product((30.0, 40.0, 50.0), (1.0, 1.5, 2.0), (2.0, 3.0, 4.0)):
        grid.append({"entry_score": es, "stop_atr": sa, "target_atr": ta})
    return grid


def optimize(df: pd.DataFrame, grid: List[dict], *, min_trades: int = 8) -> dict:
    """Best parameters on THIS (in-sample) slice, by expectancy after costs."""
    best, best_exp = grid[len(grid) // 2], float("-inf")   # default = middle of grid
    for params in grid:
        card = backtest(df, capital=10000, **params)
        if card.trades >= min_trades and card.expectancy > best_exp:
            best_exp, best = card.expectancy, params
    return best


def walk_forward(df: pd.DataFrame, *, symbol: str = "", in_bars: int = 300,
                 out_bars: int = 100, capital: float = 10000.0,
                 grid: Optional[List[dict]] = None) -> Tuple[Scorecard, List[dict]]:
    """Roll optimize-then-test across history. Returns (out-of-sample aggregate,
    per-window records). Only out-of-sample results count."""
    grid = grid or default_grid()
    oos_cards: List[Scorecard] = []
    windows: List[dict] = []
    i = 0
    while i + in_bars + out_bars <= len(df):
        insample = df.iloc[i:i + in_bars]
        oos = df.iloc[i + in_bars:i + in_bars + out_bars]
        best = optimize(insample, grid)
        card = backtest(oos, symbol=symbol, capital=capital, **best)
        oos_cards.append(card)
        windows.append({"params": best, "oos_trades": card.trades,
                        "oos_expectancy": round(card.expectancy, 2),
                        "oos_return_pct": round(card.total_return_pct, 2)})
        i += out_bars
    agg = combine([c for c in oos_cards if c.trades], capital)
    agg.symbol = symbol or "OUT-OF-SAMPLE"
    return agg, windows


def validate_wf(symbols: List[str], *, capital: float = 10000.0, period: str = "60d",
                interval: str = "15m", **kw) -> Tuple[Scorecard, List[Scorecard]]:
    from data_market_api import MarketDataClient, MarketAPIError
    market = MarketDataClient()
    per: List[Scorecard] = []
    per_cap = capital / max(1, len(symbols))
    for sym in symbols:
        try:
            df = market.get_candles(sym, period=period, interval=interval)
            agg, _ = walk_forward(df, symbol=sym, capital=per_cap, **kw)
            per.append(agg)
        except (MarketAPIError, Exception) as e:  # noqa: BLE001
            per.append(Scorecard(symbol=sym, note=f"skipped: {e}"))
    return combine([c for c in per if c.trades], capital), per


def main(argv=None) -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Walk-forward test: the honest edge check")
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA,AMZN,GOOGL")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--period", default="60d")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--in-bars", type=int, default=300)
    ap.add_argument("--out-bars", type=int, default=100)
    args = ap.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    print(f"Walk-forward on {len(symbols)} symbols ({args.period}/{args.interval}) — "
          f"optimize on {args.in_bars} bars, test on the next {args.out_bars}, roll ...\n")
    portfolio, per = validate_wf(symbols, capital=args.capital, period=args.period,
                                 interval=args.interval, in_bars=args.in_bars,
                                 out_bars=args.out_bars)
    for c in per:
        print("  " + (str(c) if c.trades else f"[{c.symbol}] {c.note}"))
    print("\n" + "=" * 72)
    print("  OUT-OF-SAMPLE " + str(portfolio))
    print("=" * 72)
    print("\n  VERDICT (on data the strategy never saw when tuned): " + portfolio.verdict())
    print("\n  (This is the honest test. Even so — paper-trade before real money.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
