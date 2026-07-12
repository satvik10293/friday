"""
Tests for the Market Data layer.

Network-dependent tests (anything calling real yfinance) are marked and
skipped if there's no internet access in the test environment — but the
parsing/indicator logic is tested with synthetic data so it always runs.
"""

import pandas as pd
import pytest

from data_market_api import MarketDataClient, MarketAPIError


@pytest.fixture
def client():
    return MarketDataClient()


def test_rsi_calculation_known_values(client):
    # Monotonically increasing series -> RSI should approach 100
    prices = pd.Series(range(1, 30))
    rsi = client._rsi(prices, period=14)
    assert rsi.dropna().iloc[-1] > 95


def test_with_indicators_adds_expected_columns(client):
    df = pd.DataFrame(
        {
            "open": range(1, 60),
            "high": range(2, 61),
            "low": range(0, 59),
            "close": range(1, 60),
            "volume": [1000] * 59,
        }
    )
    out = client.with_indicators(df)
    for col in ("sma20", "sma50", "ema20", "rsi14"):
        assert col in out.columns
    # sma50 should be NaN until we have 50 rows
    assert out["sma50"].iloc[48] != out["sma50"].iloc[48]  # NaN check


def test_get_orderbook_returns_none_not_fake_data(client):
    # Critical: must not silently fabricate order book depth.
    assert client.get_orderbook("AAPL") is None


@pytest.mark.network
def test_get_quote_live_us_symbol(client):
    quote = client.get_quote("AAPL")
    assert quote.symbol == "AAPL"
    assert quote.price > 0


@pytest.mark.network
def test_get_quote_live_nse_symbol(client):
    quote = client.get_quote("RELIANCE.NS")
    assert quote.price > 0


@pytest.mark.network
def test_get_candles_invalid_symbol_raises(client):
    with pytest.raises(MarketAPIError):
        client.get_candles("THIS_IS_NOT_A_REAL_SYMBOL_XYZ123")
