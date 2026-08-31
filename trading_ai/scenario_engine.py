"""
trading_ai/scenario_engine.py — Athena's fast trade strategist.

Given a chart she does NOT run a handful of naive checks. She:
  1. enumerates every plausible trade — long and short, across breakout, pullback,
     reversal and mean-reversion setups, at several target distances, plus WAIT;
  2. simulates thousands of possible future price paths, grounded in THIS
     instrument's own recent volatility (bootstrapped returns), so the paths look
     like how it actually moves;
  3. for each candidate, measures how often the path hits the target before the
     stop and the full profit-and-loss distribution;
  4. ranks every candidate by EXPECTED PROFIT and returns the maximum-EV plan.

It is a Monte-Carlo search over outcomes, vectorized so the whole thing runs in a
fraction of a second (well inside "a few seconds"). Honest: it optimizes expected
value under a simulated distribution — it does not predict the future, and WAIT
wins whenever no trade has a positive edge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import pandas as pd

from signals_catalog import indicators

_DEFAULT_PATHS = 4000
_DEFAULT_HORIZON = 24            # bars ahead to simulate


@dataclass
class TradePlan:
    direction: str                # long | short | wait
    setup: str
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def reward(self) -> float:
        return abs(self.target - self.entry)

    @property
    def rr(self) -> float:
        return self.reward / self.risk if self.risk > 0 else 0.0


@dataclass
class Scenario:
    plan: TradePlan
    win_prob: float                # P(target before stop)
    loss_prob: float
    timeout_prob: float
    expected_r: float              # EV in multiples of the risk
    ev_per_share: float            # expected profit per share/contract
    def to_dict(self) -> dict:
        p = self.plan
        return {"direction": p.direction, "setup": p.setup,
                "entry": round(p.entry, 4), "stop": round(p.stop, 4),
                "target": round(p.target, 4), "rr": round(p.rr, 2),
                "win_prob": round(self.win_prob, 3), "expected_R": round(self.expected_r, 3),
                "ev_per_share": round(self.ev_per_share, 4)}


@dataclass
class PositionSize:
    shares: float                  # how many to trade
    dollar_risk: float             # lost if the stop hits
    dollar_reward: float           # made if the target hits
    notional: float                # position value at entry
    capped: bool = False           # True if the account (no leverage) limited the size
    def to_dict(self) -> dict:
        return {"shares": round(self.shares, 4), "dollar_risk": round(self.dollar_risk, 2),
                "dollar_reward": round(self.dollar_reward, 2),
                "notional": round(self.notional, 2), "capped": self.capped}


@dataclass
class Strategy:
    best: Optional[Scenario]
    action: str                    # BUY | SELL | WAIT
    ranked: List[Scenario] = field(default_factory=list)
    ms: float = 0.0
    n_paths: int = 0
    n_candidates: int = 0
    size: Optional[PositionSize] = None    # set when an account size is given


def size_position(plan: TradePlan, account: float, risk_pct: float = 0.01,
                  max_leverage: float = 1.0) -> Optional[PositionSize]:
    """Shares to trade so a stop-out loses `risk_pct` of the account — sizing off
    the stop distance, the disciplined way. Capped so notional never exceeds
    account × max_leverage (default 1.0 = cash, no leverage); when a tight stop
    would need more than that, the size (and therefore the risk) is reduced."""
    if plan.direction == "wait" or plan.risk <= 0 or account <= 0:
        return None
    risk_shares = (account * max(0.0, risk_pct)) / plan.risk
    max_shares = (account * max_leverage) / plan.entry if plan.entry > 0 else risk_shares
    capped = risk_shares > max_shares
    shares = min(risk_shares, max_shares)
    return PositionSize(shares=shares, dollar_risk=shares * plan.risk,
                        dollar_reward=shares * plan.reward, notional=shares * plan.entry,
                        capped=capped)


# ── candidate trades ──────────────────────────────────────────────────────────

def enumerate_plans(df: pd.DataFrame) -> List[TradePlan]:
    """Every plausible trade to consider, built from price + ATR + structure."""
    d = indicators(df)
    price = float(d["close"].iloc[-1])
    atr = float(d["atr14"].iloc[-1] or 0.0)
    if atr <= 0:
        atr = max(price * 0.01, 1e-6)
    hi = float(d["high"].iloc[-20:].max())
    lo = float(d["low"].iloc[-20:].min())
    ema = float(d["ema20"].iloc[-1] or price)

    plans: List[TradePlan] = [TradePlan("wait", "no trade")]
    stop_mult = 1.5
    for tmult in (2.0, 3.0, 4.0):                     # search several targets (R:R)
        # long setups
        plans.append(TradePlan("long", "breakout",
                               entry=max(price, hi), stop=max(price, hi) - stop_mult * atr,
                               target=max(price, hi) + tmult * atr))
        plans.append(TradePlan("long", "pullback",
                               entry=price, stop=price - stop_mult * atr,
                               target=price + tmult * atr))
        # short setups
        plans.append(TradePlan("short", "breakdown",
                               entry=min(price, lo), stop=min(price, lo) + stop_mult * atr,
                               target=min(price, lo) - tmult * atr))
        plans.append(TradePlan("short", "reversal",
                               entry=price, stop=price + stop_mult * atr,
                               target=price - tmult * atr))
    # mean reversion toward the moving average
    if price < ema:
        plans.append(TradePlan("long", "mean_reversion", entry=price,
                               stop=price - stop_mult * atr, target=ema))
    elif price > ema:
        plans.append(TradePlan("short", "mean_reversion", entry=price,
                               stop=price + stop_mult * atr, target=ema))
    return plans


# ── outcome simulation (vectorized Monte Carlo) ───────────────────────────────

def simulate_paths(df: pd.DataFrame, *, horizon: int = _DEFAULT_HORIZON,
                   n: int = _DEFAULT_PATHS, seed: int = 0) -> np.ndarray:
    """n simulated future price paths (n, horizon), bootstrapped from the
    instrument's own recent bar-to-bar returns so volatility/drift are realistic."""
    close = df["close"].to_numpy(float)
    rets = np.diff(np.log(np.clip(close[-120:], 1e-9, None)))
    if rets.size < 5:
        rets = np.array([0.0, 0.001, -0.001])
    rng = np.random.default_rng(seed)
    draws = rng.choice(rets, size=(n, horizon), replace=True)
    price = float(close[-1])
    return price * np.exp(np.cumsum(draws, axis=1))


def _first_hit(paths: np.ndarray, level: float, *, above: bool) -> np.ndarray:
    """First bar index each path crosses `level` (>= if above else <=), or horizon."""
    cond = paths >= level if above else paths <= level
    hit = cond.any(axis=1)
    return np.where(hit, cond.argmax(axis=1), paths.shape[1])


def evaluate(plan: TradePlan, paths: np.ndarray) -> Scenario:
    """Score one plan against the simulated outcome distribution."""
    if plan.direction == "wait" or plan.risk <= 0:
        return Scenario(plan, 0.0, 0.0, 1.0, 0.0, 0.0)
    long = plan.direction == "long"
    t_idx = _first_hit(paths, plan.target, above=long)
    s_idx = _first_hit(paths, plan.stop, above=not long)
    H = paths.shape[1]
    win = (t_idx < s_idx) & (t_idx < H)
    loss = (s_idx < t_idx) & (s_idx < H)
    timeout = ~(win | loss)
    reward, risk = plan.reward, plan.risk
    # realized P&L per path: +reward if target first, -risk if stop first,
    # else mark-to-market at the final simulated price (the honest timeout case)
    final = paths[:, -1]
    mtm = (final - plan.entry) if long else (plan.entry - final)
    pnl = np.where(win, reward, np.where(loss, -risk, mtm))
    ev = float(pnl.mean())
    return Scenario(plan, float(win.mean()), float(loss.mean()), float(timeout.mean()),
                    ev / risk if risk else 0.0, ev)


# ── the strategist: search every trade, pick the max-profit one ───────────────

def best_trade(df: pd.DataFrame, *, n_paths: int = _DEFAULT_PATHS,
               horizon: int = _DEFAULT_HORIZON, min_ev_r: float = 0.10,
               account: Optional[float] = None, risk_pct: float = 0.01,
               seed: int = 0) -> Strategy:
    """Enumerate every candidate trade, simulate outcomes once, score all, and
    return the maximum-expected-profit plan. WAIT wins if nothing has an edge.
    Pass `account` to also size the position for `risk_pct` risk per trade."""
    t0 = time.perf_counter()
    if df is None or len(df) < 40:
        return Strategy(best=None, action="WAIT", ms=0.0, n_paths=0, n_candidates=0)
    plans = enumerate_plans(df)
    paths = simulate_paths(df, horizon=horizon, n=n_paths, seed=seed)
    scored = [evaluate(p, paths) for p in plans]
    scored.sort(key=lambda s: s.ev_per_share, reverse=True)
    best = scored[0]
    # only act if the best trade clears a minimum expected edge (in R)
    if best.plan.direction == "wait" or best.expected_r < min_ev_r:
        action = "WAIT"
        best = next((s for s in scored if s.plan.direction != "wait"), best)
    else:
        action = "BUY" if best.plan.direction == "long" else "SELL"
    size = (size_position(best.plan, account, risk_pct)
            if account and action != "WAIT" else None)
    return Strategy(best=best, action=action, ranked=scored,
                    ms=(time.perf_counter() - t0) * 1000.0,
                    n_paths=n_paths, n_candidates=len(plans), size=size)


def summarize(strategy: Strategy) -> str:
    """A short spoken-style summary of the max-profit plan."""
    if strategy.best is None:
        return "No tradeable data."
    b = strategy.best
    p = b.plan
    if strategy.action == "WAIT":
        return (f"WAIT — best of {strategy.n_candidates} candidates only had "
                f"{b.expected_r:+.2f}R edge; no trade worth the risk right now.")
    line = (f"{strategy.action} ({p.setup}) @ {p.entry:.2f}, stop {p.stop:.2f}, "
            f"target {p.target:.2f} (1:{p.rr:.1f} R:R). Simulated win {b.win_prob*100:.0f}%, "
            f"expected {b.expected_r:+.2f}R (best of {strategy.n_candidates} trades, "
            f"{strategy.n_paths} paths, {strategy.ms:.0f} ms).")
    if strategy.size is not None:
        sz = strategy.size
        line += (f" Size: {sz.shares:.0f} shares — risk ${sz.dollar_risk:.0f}, "
                 f"target +${sz.dollar_reward:.0f} (notional ${sz.notional:.0f}).")
        if sz.capped:
            line += " (size capped by account — stop too tight for the full risk budget.)"
    return line
