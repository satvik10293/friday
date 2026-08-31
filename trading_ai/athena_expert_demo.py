"""
athena_expert_demo.py — see a chart, then read Athena's expert take on it.

Pulls a symbol's candles (real, via yfinance; synthetic fallback if offline),
renders the chart to a PNG you can open, and prints her full read using the new
brain: every detected signal WITH why-it-happens and how-to-trade (entry / take-
profit / stop), plus the trained chart-vision model's bias.

    python athena_expert_demo.py --symbol AAPL
    python athena_expert_demo.py --symbol TSLA --period 1mo --interval 1h
    python athena_expert_demo.py --offline        # no network; synthetic chart

Observe-only: this reads and explains. It never places a trade.
"""

from __future__ import annotations

import argparse
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from trading_knowledge import explain_chart, explain  # noqa: E402
from signals_catalog import indicators  # noqa: E402

# the lessons use — and ≥; make the console tolerate them instead of crashing
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _load(symbol: str, period: str, interval: str, offline: bool):
    if not offline:
        try:
            from data_market_api import MarketDataClient
            df = MarketDataClient().get_candles(symbol, period=period, interval=interval)
            if len(df) >= 40:
                return df, "live (yfinance)"
        except Exception as e:  # noqa: BLE001 — fall back, never crash the demo
            print(f"[data] live fetch failed ({e}); using a synthetic chart instead.")
    from vision_model.dataset import synth_ohlcv
    drift = np.random.default_rng().choice([-0.7, -0.3, 0.3, 0.7])
    return synth_ohlcv(bars=120, drift=float(drift), vol=1.0,
                       seed=int(np.random.default_rng().integers(1e9))), "synthetic"


def _render_png(df, symbol: str, path: str) -> None:
    d = df.iloc[-90:].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(12, 6))
    for i, row in d.iterrows():
        up = row["close"] >= row["open"]
        color = "#16a34a" if up else "#dc2626"
        ax.plot([i, i], [row["low"], row["high"]], color=color, linewidth=0.8, zorder=1)
        h = abs(row["close"] - row["open"]) or (row["high"] - row["low"]) * 0.02
        ax.add_patch(plt.Rectangle((i - 0.3, min(row["open"], row["close"])), 0.6, h,
                                   color=color, zorder=2))
    di = indicators(df).iloc[-90:].reset_index(drop=True)
    ax.plot(di.index, di["ema20"], color="#2563eb", linewidth=1.0, label="EMA20")
    ax.plot(di.index, di["ema50"], color="#f59e0b", linewidth=1.0, label="EMA50")
    ax.set_title(f"{symbol} — Athena's chart")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _print_read(symbol: str, source: str, df, account: float = 0.0) -> None:
    read = explain_chart(df)
    print("\n" + "=" * 68)
    print(f"  ATHENA'S READ — {symbol}   [{source} data, {len(df)} candles]")
    print("=" * 68)
    print(f"  Overall bias: {read['bias'].upper()}   (net score {read['score']}, "
          f"{read['count']} signals)")

    # vision model (if trained weights are present)
    try:
        from vision_model.predict import ChartPredictor
        p = ChartPredictor("out/chartnet.pt")
        if p.available():
            v = p.predict_df(df)
            print(f"  Chart-vision model: {v['class'].upper()} "
                  f"(confidence {v['confidence']})")
        else:
            print("  Chart-vision model: not trained yet "
                  "(run: python -m vision_model.train)")
    except Exception as e:  # noqa: BLE001
        print(f"  Chart-vision model: unavailable ({e})")

    if not read["signals"]:
        print("\n  No notable signals on this window right now.")
        return
    print("\n  What she sees, and how she'd trade each:\n")
    for s in read["signals"]:
        arrow = "UP" if s["direction"] > 0 else "DOWN" if s["direction"] < 0 else "--"
        print(f"  • {s['name']}  [{arrow}, {s['kind']}]")
        if s.get("why"):
            print(f"      why : {s['why']}")
        if s.get("entry"):
            print(f"      in  : {s['entry']}")
        if s.get("take_profit"):
            print(f"      tp  : {s['take_profit']}")
        if s.get("stop_loss"):
            print(f"      stop: {s['stop_loss']}")
        print()
    # a concrete risk frame from ATR
    d = indicators(df)
    atr = float(d["atr14"].iloc[-1] or 0.0)
    price = float(d["close"].iloc[-1])
    if atr > 0:
        print(f"  Risk frame @ {price:.2f}: ATR={atr:.2f} → a ~1.5x ATR stop is "
              f"{1.5*atr:.2f} away; aim ~2R target ({3*atr:.2f}).")

    # strategist: simulate every trade's outcomes, pick the max-expected-profit one
    try:
        from scenario_engine import best_trade, summarize
        strat = best_trade(df, account=(account or None))
        print(f"\n  STRATEGIST — searched {strat.n_candidates} trades × "
              f"{strat.n_paths} simulated paths in {strat.ms:.0f} ms:")
        print(f"    → {summarize(strat)}")
        top = [sc for sc in strat.ranked if sc.plan.direction != 'wait'][:3]
        if top:
            print("    Top candidates by expected profit:")
            for sc in top:
                dd = sc.to_dict()
                print(f"      {dd['direction']:5} {dd['setup']:14} "
                      f"EV {dd['expected_R']:+.2f}R | win {dd['win_prob']*100:4.0f}% | "
                      f"R:R 1:{dd['rr']}")
    except Exception as e:  # noqa: BLE001
        print(f"  Strategist unavailable: {e}")

    print("\n  (Observe-only. Every setup is probabilistic — size small, honor the stop.)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Test Athena's expert chart read")
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--period", default="5d")
    ap.add_argument("--interval", default="15m")
    ap.add_argument("--offline", action="store_true", help="use a synthetic chart")
    ap.add_argument("--account", type=float, default=0.0,
                    help="account size to size the position (risks 1%% per trade)")
    ap.add_argument("--no-open", action="store_true", help="don't auto-open the PNG")
    args = ap.parse_args(argv)

    df, source = _load(args.symbol, args.period, args.interval, args.offline)
    png = os.path.abspath(f"athena_{args.symbol.replace('.', '_')}.png")
    _render_png(df, args.symbol, png)
    print(f"[chart] saved {png}")
    _print_read(args.symbol, source, df, account=args.account)
    if not args.no_open:
        try:
            os.startfile(png)  # Windows: opens the chart in the default viewer
        except Exception:  # noqa: BLE001
            print(f"[chart] open it manually: {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
