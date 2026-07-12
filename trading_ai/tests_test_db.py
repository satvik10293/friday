import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from data_db import Database


@pytest.fixture
def db(tmp_path):
    return Database(path=tmp_path / "test.db")


def test_schema_creates_all_tables(db):
    with db.connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {"candles", "user_actions", "trade_journal", "strategy_scores"} <= tables


def test_upsert_candles(db):
    idx = pd.date_range("2026-01-01", periods=3, freq="5min")
    df = pd.DataFrame(
        {
            "open": [1.0, 2.0, 3.0],
            "high": [1.5, 2.5, 3.5],
            "low": [0.5, 1.5, 2.5],
            "close": [1.2, 2.2, 3.2],
            "volume": [100, 200, 300],
        },
        index=idx,
    )
    n = db.upsert_candles("AAPL", "5m", df)
    assert n == 3
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM candles").fetchone()["c"]
    assert count == 3


def test_log_action(db):
    action_id = db.log_action("AAPL", "buy", price=150.0, reason="breakout")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_actions WHERE id = ?", (action_id,)
        ).fetchone()
    assert row["action"] == "BUY"
    assert row["price"] == 150.0


def test_open_and_close_trade_computes_pnl(db):
    trade_id = db.open_trade("AAPL", entry_price=100.0, direction="LONG", setup_tag="breakout")
    db.close_trade(trade_id, exit_price=110.0)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM trade_journal WHERE id = ?", (trade_id,)
        ).fetchone()
    assert row["profit_loss"] == 10.0
    assert row["exit_price"] == 110.0


def test_close_short_trade_pnl_direction(db):
    trade_id = db.open_trade("AAPL", entry_price=100.0, direction="SHORT")
    db.close_trade(trade_id, exit_price=90.0)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT profit_loss FROM trade_journal WHERE id = ?", (trade_id,)
        ).fetchone()
    assert row["profit_loss"] == 10.0  # short profits when price drops


def test_close_trade_unknown_id_raises(db):
    with pytest.raises(ValueError):
        db.close_trade(9999, exit_price=1.0)


def test_strategy_score_updates_confidence(db):
    db.update_strategy_score("breakout", won=True)
    db.update_strategy_score("breakout", won=True)
    db.update_strategy_score("breakout", won=False)
    row = db.get_strategy_score("breakout")
    assert row["wins"] == 2
    assert row["losses"] == 1
    assert abs(row["confidence"] - (2 / 3)) < 1e-6
