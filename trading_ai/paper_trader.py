"""
trading_ai/paper_trader.py — Athena trades on paper (fake money, real prices).

She takes her real BUY/SELL calls against live prices with a virtual account, so
you see an honest P&L and she LEARNS from every closed trade (via the existing
OutcomeTracker → strategy scorer) — with zero real money at risk. This is the
safe place to find out whether she has an edge before a single real rupee moves.

    python paper_trader.py --symbols AAPL,MSFT,NVDA --capital 10000 --cycles 0
        (cycles 0 = run forever; Ctrl+C to stop. State persists between runs.)

Not financial advice. Paper results are the audition, not a guarantee.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parent
_DEFAULT_STATE = _ROOT.parent / "data" / "paper_portfolio.json"


@dataclass
class Position:
    symbol: str
    direction: str                 # long | short
    entry: float
    stop: float
    target: float
    shares: float
    opened_at: str = ""

    def unrealized(self, price: float) -> float:
        return (price - self.entry) * self.shares * (1 if self.direction == "long" else -1)


@dataclass
class PaperTrader:
    capital: float = 10000.0
    risk_pct: float = 0.01
    fee_bps: float = 5.0
    slippage_bps: float = 5.0
    cash: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    closed: List[dict] = field(default_factory=list)   # {symbol, pnl, r, result}
    path: Optional[Path] = None

    def __post_init__(self):
        if not self.cash:
            self.cash = self.capital
        if self.path is None:
            self.path = _DEFAULT_STATE
        self._load()

    # ── money ──────────────────────────────────────────────────────────────────
    @property
    def _cost_rate(self) -> float:
        return (self.fee_bps + self.slippage_bps) / 10000.0

    def unrealized(self, prices: Dict[str, float]) -> float:
        return sum(p.unrealized(prices.get(s, p.entry)) for s, p in self.positions.items())

    def equity(self, prices: Dict[str, float]) -> float:
        return self.cash + self.unrealized(prices)

    # ── open a paper trade on a real signal ────────────────────────────────────
    def consider(self, symbol: str, action: str, plan, prices: Dict[str, float]) -> Optional[str]:
        """Open a paper position if she signals BUY/SELL and we're flat on it."""
        if symbol in self.positions or action not in ("BUY", "SELL") or plan is None:
            return None
        entry = float(getattr(plan, "entry", 0.0))
        stop = float(getattr(plan, "stop_loss", 0.0))
        target = float(getattr(plan, "target", 0.0))
        risk_ps = abs(entry - stop)
        if entry <= 0 or risk_ps <= 0:
            return None
        eq = self.equity(prices)
        shares = min((eq * self.risk_pct) / risk_ps, eq / entry)   # risk-sized, no leverage
        if shares <= 0:
            return None
        self.cash -= entry * shares * self._cost_rate               # entry cost
        self.positions[symbol] = Position(
            symbol, "long" if action == "BUY" else "short", entry, stop, target,
            shares, time.strftime("%Y-%m-%d %H:%M"))
        self._save()
        return (f"OPEN {action} {shares:.0f} {symbol} @ {entry:.2f} "
                f"(stop {stop:.2f}, target {target:.2f})")

    # ── mark open positions to the live price; close on stop/target ────────────
    def mark(self, symbol: str, price: float) -> Optional[str]:
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        long = pos.direction == "long"
        hit = None
        if long:
            hit = "stop" if price <= pos.stop else ("target" if price >= pos.target else None)
        else:
            hit = "stop" if price >= pos.stop else ("target" if price <= pos.target else None)
        if hit is None:
            return None
        exit_price = pos.stop if hit == "stop" else pos.target
        gross = pos.unrealized(exit_price)
        cost = exit_price * pos.shares * self._cost_rate
        pnl = gross - cost
        self.cash += pnl
        r = pnl / (abs(pos.entry - pos.stop) * pos.shares) if pos.shares else 0.0
        result = "WIN" if pnl > 0 else "LOSS"
        self.closed.append({"symbol": symbol, "pnl": round(pnl, 2), "r": round(r, 2),
                            "result": result})
        del self.positions[symbol]
        self._save()
        return (f"CLOSE {symbol} @ {exit_price:.2f} — {hit.upper()} ({result}) — "
                f"P&L ${pnl:+.2f} ({r:+.2f}R)")

    # ── the honest live scorecard ──────────────────────────────────────────────
    def report(self, prices: Optional[Dict[str, float]] = None) -> dict:
        prices = prices or {}
        n = len(self.closed)
        wins = [t for t in self.closed if t["pnl"] > 0]
        realized = sum(t["pnl"] for t in self.closed)
        eq = self.equity(prices)
        return {
            "equity": round(eq, 2), "cash": round(self.cash, 2),
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(self.unrealized(prices), 2),
            "return_pct": round((eq - self.capital) / self.capital * 100, 2) if self.capital else 0,
            "trades": n, "wins": len(wins),
            "win_rate": round(len(wins) / n, 3) if n else 0.0,
            "open_positions": {s: p.direction for s, p in self.positions.items()},
        }

    # ── persistence (never raises) ─────────────────────────────────────────────
    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "capital": self.capital, "cash": self.cash,
                "positions": {s: p.__dict__ for s, p in self.positions.items()},
                "closed": self.closed}, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _load(self) -> None:
        try:
            if self.path and self.path.exists():
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self.capital = d.get("capital", self.capital)
                self.cash = d.get("cash", self.cash)
                self.closed = d.get("closed", [])
                self.positions = {s: Position(**v) for s, v in d.get("positions", {}).items()}
        except (OSError, ValueError, TypeError):
            pass


def run_live(symbols: List[str], *, capital: float = 10000.0, cycles: int = 0,
             interval: float = 30.0, state: Optional[Path] = None) -> None:
    """Live paper-trading loop: real prices, her real calls, virtual money, and
    the OutcomeTracker learning from every close. cycles=0 runs forever."""
    from data_market_api import MarketDataClient
    from recommend_recommendation_engine import RecommendationEngine
    from learning_outcome_tracker import OutcomeTracker
    from data_db import Database

    market = MarketDataClient()
    db = Database()
    engine = RecommendationEngine(market=market, db=db)
    tracker = OutcomeTracker(db=db)
    trader = PaperTrader(capital=capital, path=state)

    print(f"Paper trading {symbols} | ${capital:,.0f} virtual | learning ON | "
          f"{'forever' if cycles == 0 else cycles} cycles")
    c = 0
    while cycles == 0 or c < cycles:
        c += 1
        prices = {}
        for sym in symbols:
            try:
                price = float(market.get_quote(sym).price)
                prices[sym] = price
                closed = trader.mark(sym, price)
                if closed:
                    print("  " + closed)
                    tracker.check(sym, price)               # she learns from the close
                rec = engine.evaluate(sym)
                opened = trader.consider(sym, rec.action, rec.plan, prices)
                if opened:
                    print("  " + opened)
                    tracker.track(sym, rec.action, rec.plan, "paper")
            except Exception as e:  # noqa: BLE001 — one symbol failing can't stop the loop
                print(f"  [{sym}] skipped: {e}")
        r = trader.report(prices)
        print(f"[cycle {c}] equity ${r['equity']:,.2f} ({r['return_pct']:+.2f}%) | "
              f"{r['trades']} closed, {r['win_rate']*100:.0f}% win | "
              f"open: {list(r['open_positions'])}")
        if cycles == 0 or c < cycles:
            time.sleep(interval)


def main(argv=None) -> int:
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Paper-trade Athena (fake money, real prices)")
    ap.add_argument("--symbols", default="AAPL,MSFT,NVDA")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--cycles", type=int, default=0, help="0 = run forever")
    ap.add_argument("--interval", type=float, default=30.0)
    args = ap.parse_args(argv)
    run_live([s.strip() for s in args.symbols.split(",") if s.strip()],
             capital=args.capital, cycles=args.cycles, interval=args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
