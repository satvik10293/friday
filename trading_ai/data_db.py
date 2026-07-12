"""
SQLite storage layer shared across the app.

Tables:
  candles        - cached OHLCV history per symbol/interval
  user_actions   - raw log of observed user actions (buy/sell/hold/close)
  trade_journal  - completed trades with entry/exit/P&L/screenshot path
  strategy_scores- running win/loss tally per named setup (for learning engine)
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

DEFAULT_DB_PATH = Path(__file__).parent / "trading_assistant.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    ts TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    PRIMARY KEY (symbol, interval, ts)
);

CREATE TABLE IF NOT EXISTS user_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,         -- BUY, SELL, HOLD, CLOSE
    price REAL,
    reason TEXT,
    source TEXT DEFAULT 'screen'  -- 'screen' (observed via vision) or 'manual'
);

CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    entry_price REAL NOT NULL,
    exit_price REAL,
    direction TEXT NOT NULL,      -- LONG or SHORT
    profit_loss REAL,
    duration_seconds INTEGER,
    setup_tag TEXT,               -- e.g. 'breakout', 'support_bounce'
    screenshot_path TEXT,
    market_conditions TEXT        -- free-text / JSON snapshot
);

CREATE TABLE IF NOT EXISTS strategy_scores (
    setup_tag TEXT PRIMARY KEY,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.5
);
"""


class Database:
    def __init__(self, path: Path = DEFAULT_DB_PATH):
        self.path = path
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- Candles ----------

    def upsert_candles(self, symbol: str, interval: str, df) -> int:
        rows = [
            (
                symbol,
                interval,
                ts.isoformat(),
                float(row.open),
                float(row.high),
                float(row.low),
                float(row.close),
                int(row.volume),
            )
            for ts, row in df.iterrows()
        ]
        with self.connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO candles
                   (symbol, interval, ts, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
        return len(rows)

    # ---------- User actions ----------

    def log_action(
        self,
        symbol: str,
        action: str,
        price: Optional[float] = None,
        reason: str = "",
        source: str = "screen",
        timestamp: Optional[datetime] = None,
    ) -> int:
        ts = (timestamp or datetime.now()).isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO user_actions (timestamp, symbol, action, price, reason, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ts, symbol, action.upper(), price, reason, source),
            )
            return cur.lastrowid

    # ---------- Trade journal ----------

    def open_trade(
        self,
        symbol: str,
        entry_price: float,
        direction: str = "LONG",
        setup_tag: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        market_conditions: Optional[str] = None,
        entry_time: Optional[datetime] = None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """INSERT INTO trade_journal
                   (symbol, entry_time, entry_price, direction, setup_tag,
                    screenshot_path, market_conditions)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    symbol,
                    (entry_time or datetime.now()).isoformat(),
                    entry_price,
                    direction,
                    setup_tag,
                    screenshot_path,
                    market_conditions,
                ),
            )
            return cur.lastrowid

    def close_trade(
        self, trade_id: int, exit_price: float, exit_time: Optional[datetime] = None
    ) -> None:
        exit_time = exit_time or datetime.now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT entry_time, entry_price, direction FROM trade_journal WHERE id = ?",
                (trade_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"No trade with id {trade_id}")
            entry_time = datetime.fromisoformat(row["entry_time"])
            entry_price = row["entry_price"]
            direction = row["direction"]
            pnl = (
                (exit_price - entry_price)
                if direction == "LONG"
                else (entry_price - exit_price)
            )
            duration = int((exit_time - entry_time).total_seconds())
            conn.execute(
                """UPDATE trade_journal
                   SET exit_time = ?, exit_price = ?, profit_loss = ?, duration_seconds = ?
                   WHERE id = ?""",
                (exit_time.isoformat(), exit_price, pnl, duration, trade_id),
            )

    # ---------- Strategy scoring (used by Learning Engine) ----------

    def update_strategy_score(self, setup_tag: str, won: bool) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO strategy_scores (setup_tag) VALUES (?)",
                (setup_tag,),
            )
            col = "wins" if won else "losses"
            conn.execute(
                f"UPDATE strategy_scores SET {col} = {col} + 1 WHERE setup_tag = ?",
                (setup_tag,),
            )
            row = conn.execute(
                "SELECT wins, losses FROM strategy_scores WHERE setup_tag = ?",
                (setup_tag,),
            ).fetchone()
            total = row["wins"] + row["losses"]
            confidence = row["wins"] / total if total else 0.5
            conn.execute(
                "UPDATE strategy_scores SET confidence = ? WHERE setup_tag = ?",
                (confidence, setup_tag),
            )

    def get_strategy_score(self, setup_tag: str) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM strategy_scores WHERE setup_tag = ?", (setup_tag,)
            ).fetchone()
