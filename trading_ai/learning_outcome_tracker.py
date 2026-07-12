"""
Phase 4 — Learning Engine: Outcome Tracker.

Closes the learning loop. Every BUY/SELL the engine announces comes with a
trade plan (entry / stop-loss / target). This module records that call as a
paper trade and then watches live prices to see how it actually ended:

    target hit first  -> WIN
    stop hit first    -> LOSS
    too old (48h)     -> EXPIRED (scored by whether it was up or down)

Each closed call updates strategy_scores — the same table the
Recommendation Engine reads to boost or shrink its confidence. So from now
on, every call Athena makes teaches it something: setups that keep losing
get their scores dragged down and stop being recommended; setups that win
earn more confidence. That's the "learning" in learning engine — measured
from its own track record, not hardcoded.

These are PAPER outcomes: nothing here places trades. It only grades the
advice that was given.

Calls survive restarts (stored in SQLite next to everything else).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from data_db import Database

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tracked_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,          -- LONG or SHORT
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target REAL NOT NULL,
    setup_tag TEXT,
    opened_at TEXT NOT NULL,
    status TEXT DEFAULT 'OPEN',       -- OPEN, WIN, LOSS, EXPIRED
    closed_at TEXT,
    exit_price REAL,
    pnl_per_share REAL,
    journal_id INTEGER
);
"""


@dataclass
class CallOutcome:
    symbol: str
    direction: str
    status: str          # WIN, LOSS, EXPIRED
    entry: float
    exit_price: float
    pnl_per_share: float
    setup_tag: str

    def __str__(self) -> str:
        emoji = {"WIN": "✔", "LOSS": "✘", "EXPIRED": "~"}[self.status]
        return (f"{emoji} {self.status}: {self.direction} {self.symbol} "
                f"entry {self.entry:.2f} -> exit {self.exit_price:.2f} "
                f"({self.pnl_per_share:+.2f}/share)")


class OutcomeTracker:
    def __init__(self, db: Optional[Database] = None, max_age_hours: float = 48.0):
        self.db = db or Database()
        self.max_age = timedelta(hours=max_age_hours)
        with self.db.connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------
    # Opening calls
    # ------------------------------------------------------------------

    def track(self, symbol: str, action: str, plan, setup_tag: str,
              price: Optional[float] = None) -> Optional[int]:
        """
        Starts tracking a BUY (LONG) or SELL (SHORT) call with its plan.

        - Same-direction call already open for this symbol -> ignored
          (the engine repeats itself every rec-interval; one call is enough).
        - Opposite-direction call open -> the old call is closed at the
          current price first (the market changed its mind; grade what was).
        """
        if action not in ("BUY", "SELL") or plan is None:
            return None
        direction = "LONG" if action == "BUY" else "SHORT"

        with self.db.connect() as conn:
            existing = conn.execute(
                "SELECT id, direction FROM tracked_calls "
                "WHERE symbol = ? AND status = 'OPEN'",
                (symbol,),
            ).fetchone()

        if existing is not None:
            if existing["direction"] == direction:
                return None
            if price is not None:
                self._close(existing["id"], price, "EXPIRED", forced=True)

        journal_id = self.db.open_trade(
            symbol=symbol,
            entry_price=plan.entry,
            direction=direction,
            setup_tag=setup_tag,
            market_conditions=f"stop={plan.stop_loss:.4f} target={plan.target:.4f} "
                              f"rr={plan.rr_ratio:.2f}",
        )
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO tracked_calls
                   (symbol, direction, entry, stop_loss, target, setup_tag,
                    opened_at, journal_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, direction, plan.entry, plan.stop_loss, plan.target,
                 setup_tag, datetime.now().isoformat(), journal_id),
            )
            return cur.lastrowid

    # ------------------------------------------------------------------
    # Checking outcomes
    # ------------------------------------------------------------------

    def check(self, symbol: str, price: float,
              now: Optional[datetime] = None) -> List[CallOutcome]:
        """Grades all OPEN calls on `symbol` against the live price.
        Returns the calls that just closed (empty list most of the time)."""
        now = now or datetime.now()
        outcomes: List[CallOutcome] = []

        with self.db.connect() as conn:
            open_calls = conn.execute(
                "SELECT * FROM tracked_calls WHERE symbol = ? AND status = 'OPEN'",
                (symbol,),
            ).fetchall()

        for call in open_calls:
            status = None
            if call["direction"] == "LONG":
                if price <= call["stop_loss"]:      # stop checked first: worst case
                    status = "LOSS"
                elif price >= call["target"]:
                    status = "WIN"
            else:
                if price >= call["stop_loss"]:
                    status = "LOSS"
                elif price <= call["target"]:
                    status = "WIN"

            if status is None and now - datetime.fromisoformat(call["opened_at"]) > self.max_age:
                status = "EXPIRED"

            if status is not None:
                outcomes.append(self._close(call["id"], price, status))

        return outcomes

    def check_all(self, get_quote: Callable[[str], object],
                  exclude: Optional[str] = None) -> List[CallOutcome]:
        """Grades open calls on ALL symbols (auto mode can leave calls open on
        a chart you switched away from). get_quote failures are skipped.
        Pass exclude= for the symbol the caller already checks every cycle,
        to avoid a redundant network quote."""
        with self.db.connect() as conn:
            symbols = [r["symbol"] for r in conn.execute(
                "SELECT DISTINCT symbol FROM tracked_calls WHERE status = 'OPEN'"
            ).fetchall()]

        outcomes: List[CallOutcome] = []
        for symbol in symbols:
            if symbol == exclude:
                continue
            try:
                quote = get_quote(symbol)
            except Exception:
                continue
            outcomes.extend(self.check(symbol, quote.price))
        return outcomes

    # ------------------------------------------------------------------

    def _close(self, call_id: int, price: float, status: str,
               forced: bool = False) -> CallOutcome:
        with self.db.connect() as conn:
            call = conn.execute(
                "SELECT * FROM tracked_calls WHERE id = ?", (call_id,)
            ).fetchone()

        if call["direction"] == "LONG":
            # WIN/LOSS exits happen AT the planned level, not at the polled
            # price (we only sample every few seconds; assume the level filled)
            exit_price = {"WIN": call["target"], "LOSS": call["stop_loss"]}.get(status, price)
            pnl = exit_price - call["entry"]
        else:
            exit_price = {"WIN": call["target"], "LOSS": call["stop_loss"]}.get(status, price)
            pnl = call["entry"] - exit_price

        now = datetime.now()
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE tracked_calls
                   SET status = ?, closed_at = ?, exit_price = ?, pnl_per_share = ?
                   WHERE id = ?""",
                (status, now.isoformat(), exit_price, pnl, call_id),
            )

        if call["journal_id"] is not None:
            try:
                self.db.close_trade(call["journal_id"], exit_price, exit_time=now)
            except ValueError:
                pass  # journal row was deleted; the tracked call still counts

        # Feed the learning loop: expired/forced closes are graded by sign
        if not forced or pnl != 0:
            self.db.update_strategy_score(call["setup_tag"] or "untagged", won=pnl > 0)

        return CallOutcome(
            symbol=call["symbol"], direction=call["direction"], status=status,
            entry=call["entry"], exit_price=exit_price, pnl_per_share=pnl,
            setup_tag=call["setup_tag"] or "untagged",
        )

    # ------------------------------------------------------------------

    def stats(self) -> dict:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT
                     SUM(status = 'OPEN')  AS open_calls,
                     SUM(status = 'WIN')   AS wins,
                     SUM(status = 'LOSS')  AS losses,
                     SUM(status = 'EXPIRED') AS expired,
                     SUM(CASE WHEN status != 'OPEN' THEN pnl_per_share END) AS total_pnl
                   FROM tracked_calls"""
            ).fetchone()
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        closed = wins + losses + (row["expired"] or 0)
        return {
            "open": row["open_calls"] or 0,
            "wins": wins,
            "losses": losses,
            "expired": row["expired"] or 0,
            "closed": closed,
            "win_rate": wins / (wins + losses) if (wins + losses) else None,
            "total_pnl_per_share": row["total_pnl"] or 0.0,
        }
