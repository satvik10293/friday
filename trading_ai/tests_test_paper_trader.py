"""
Paper trading: fake money, real signals. Open on a call, close on stop/target,
honest P&L, learning-safe. All local — no network, no real money.
"""

from __future__ import annotations

from paper_trader import PaperTrader


class _Plan:
    def __init__(self, entry, stop_loss, target):
        self.entry = entry
        self.stop_loss = stop_loss
        self.target = target
        self.rr_ratio = abs(target - entry) / abs(entry - stop_loss)


def _trader(tmp_path, **kw):
    return PaperTrader(capital=10000.0, path=tmp_path / "paper.json", **kw)


def test_opens_a_risk_sized_position(tmp_path):
    t = _trader(tmp_path)
    msg = t.consider("AAPL", "BUY", _Plan(100, 98, 106), {"AAPL": 100})
    assert msg and "AAPL" in t.positions
    # risk 1% of $10k = $100; $2/share risk → 50 shares (notional $5k ≤ equity, uncapped)
    assert abs(t.positions["AAPL"].shares - 50) < 1e-6


def test_target_hit_is_a_win(tmp_path):
    t = _trader(tmp_path)
    t.consider("AAPL", "BUY", _Plan(100, 98, 106), {"AAPL": 100})
    msg = t.mark("AAPL", 106)
    assert msg and "WIN" in msg
    r = t.report({})
    assert r["trades"] == 1 and r["wins"] == 1 and r["realized_pnl"] > 0


def test_stop_hit_is_a_loss(tmp_path):
    t = _trader(tmp_path)
    t.consider("AAPL", "BUY", _Plan(100, 98, 106), {"AAPL": 100})
    msg = t.mark("AAPL", 98)
    assert msg and "LOSS" in msg
    assert t.report({})["realized_pnl"] < 0


def test_no_trade_without_signal_and_no_double_open(tmp_path):
    t = _trader(tmp_path)
    assert t.consider("AAPL", "WAIT", None, {"AAPL": 100}) is None
    t.consider("AAPL", "BUY", _Plan(100, 98, 106), {"AAPL": 100})
    assert t.consider("AAPL", "BUY", _Plan(100, 98, 106), {"AAPL": 100}) is None


def test_state_persists_across_restart(tmp_path):
    p = tmp_path / "paper.json"
    t = PaperTrader(capital=10000.0, path=p)
    t.consider("AAPL", "BUY", _Plan(100, 98, 106), {"AAPL": 100})
    t.mark("AAPL", 106)
    reborn = PaperTrader(capital=10000.0, path=p)
    assert reborn.report({})["trades"] == 1     # the closed trade survived a restart


def test_short_target_is_below_entry(tmp_path):
    t = _trader(tmp_path)
    t.consider("XYZ", "SELL", _Plan(100, 102, 94), {"XYZ": 100})
    assert t.positions["XYZ"].direction == "short"
    msg = t.mark("XYZ", 94)                       # short target = price falls
    assert msg and "WIN" in msg
