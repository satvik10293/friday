"""
The truth test: backtest with costs, honest scorecard, blunt verdict.
"""

from __future__ import annotations

from validation import Scorecard, backtest, combine
from vision_model.dataset import synth_ohlcv


def test_backtest_produces_a_scorecard():
    df = synth_ohlcv(bars=500, drift=0.3, vol=1.0, seed=1)
    card = backtest(df, capital=10000)
    assert isinstance(card, Scorecard)
    assert card.trades >= 0
    assert card.final_equity > 0


def test_costs_reduce_expectancy():
    df = synth_ohlcv(bars=600, drift=0.4, vol=1.0, seed=2)
    free = backtest(df, fee_bps=0, slippage_bps=0)
    costly = backtest(df, fee_bps=25, slippage_bps=25)
    if free.trades and costly.trades:
        assert costly.expectancy <= free.expectancy      # costs never help
        assert costly.costs_paid > 0


def test_verdict_is_honest_and_blunt():
    thin = backtest(synth_ohlcv(bars=120, drift=0.0, vol=0.2, seed=3))
    assert "NOT ENOUGH DATA" in thin.verdict()           # <30 trades
    # has_edge requires ≥30 trades AND positive expectancy AND PF>1
    assert isinstance(thin.has_edge, bool)


def test_combine_pools_symbols():
    cards = [backtest(synth_ohlcv(bars=400, drift=d, seed=i), symbol=f"S{i}", capital=5000)
             for i, d in enumerate((0.5, -0.5))]
    port = combine([c for c in cards if c.trades], capital=10000)
    assert port.symbol == "PORTFOLIO"
    assert port.trades == sum(c.trades for c in cards if c.trades)
