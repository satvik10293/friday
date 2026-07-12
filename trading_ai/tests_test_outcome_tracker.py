"""Offline tests for learning_outcome_tracker (temp SQLite per test)."""

from datetime import datetime, timedelta

import pytest

from data_db import Database
from learning_outcome_tracker import OutcomeTracker
from recommend_recommendation_engine import TradePlan


@pytest.fixture
def db(tmp_path):
    return Database(path=tmp_path / "test.db")


@pytest.fixture
def tracker(db):
    return OutcomeTracker(db=db)


def _plan(entry=100.0, stop=95.0, target=110.0):
    return TradePlan(entry=entry, stop_loss=stop, target=target,
                     risk_per_share=abs(entry - stop),
                     reward_per_share=abs(target - entry),
                     rr_ratio=abs(target - entry) / abs(entry - stop),
                     risk_pct=abs(entry - stop) / entry * 100)


def test_long_call_wins_at_target(tracker, db):
    tracker.track("AAPL", "BUY", _plan(), "trend_continuation", price=100.0)
    assert tracker.check("AAPL", 105.0) == []          # between stop and target: still open
    outcomes = tracker.check("AAPL", 111.0)            # target hit
    assert len(outcomes) == 1
    assert outcomes[0].status == "WIN"
    assert outcomes[0].pnl_per_share == pytest.approx(10.0)  # exit AT target
    score = db.get_strategy_score("trend_continuation")
    assert score["wins"] == 1 and score["losses"] == 0


def test_long_call_loses_at_stop(tracker, db):
    tracker.track("AAPL", "BUY", _plan(), "trend_continuation", price=100.0)
    outcomes = tracker.check("AAPL", 94.0)
    assert outcomes[0].status == "LOSS"
    assert outcomes[0].pnl_per_share == pytest.approx(-5.0)  # exit AT stop
    assert db.get_strategy_score("trend_continuation")["losses"] == 1


def test_short_call_wins_when_price_falls(tracker, db):
    tracker.track("BTC-USD", "SELL", _plan(entry=100.0, stop=105.0, target=90.0),
                  "breakdown", price=100.0)
    outcomes = tracker.check("BTC-USD", 89.0)
    assert outcomes[0].status == "WIN"
    assert outcomes[0].pnl_per_share == pytest.approx(10.0)


def test_repeat_same_direction_is_ignored(tracker):
    first = tracker.track("AAPL", "BUY", _plan(), "t", price=100.0)
    second = tracker.track("AAPL", "BUY", _plan(), "t", price=100.5)
    assert first is not None
    assert second is None
    assert tracker.stats()["open"] == 1


def test_opposite_signal_closes_old_call_first(tracker):
    tracker.track("AAPL", "BUY", _plan(), "t", price=100.0)
    tracker.track("AAPL", "SELL", _plan(entry=102.0, stop=106.0, target=94.0),
                  "t", price=102.0)
    stats = tracker.stats()
    assert stats["open"] == 1          # only the new SHORT remains open
    assert stats["closed"] == 1        # the LONG was force-closed


def test_stale_call_expires(tracker, db):
    tracker.track("AAPL", "BUY", _plan(), "t", price=100.0)
    later = datetime.now() + timedelta(hours=49)
    outcomes = tracker.check("AAPL", 101.0, now=later)
    assert outcomes[0].status == "EXPIRED"
    # closed up +1.0/share -> graded as a win
    assert db.get_strategy_score("t")["wins"] == 1


def test_calls_survive_restart(db):
    OutcomeTracker(db=db).track("AAPL", "BUY", _plan(), "t", price=100.0)
    resumed = OutcomeTracker(db=db)     # fresh instance, same DB
    assert resumed.stats()["open"] == 1
    assert resumed.check("AAPL", 111.0)[0].status == "WIN"


def test_stats_summary(tracker):
    tracker.track("AAPL", "BUY", _plan(), "t", price=100.0)
    tracker.check("AAPL", 111.0)                        # WIN
    tracker.track("TSLA", "BUY", _plan(), "t", price=100.0)
    tracker.check("TSLA", 94.0)                         # LOSS
    stats = tracker.stats()
    assert stats["closed"] == 2
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["total_pnl_per_share"] == pytest.approx(5.0)  # +10 - 5
