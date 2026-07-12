"""
Eye 1 — Market Data Layer.

Free, no-API-key data source using yfinance. Works for:
  - US stocks/ETFs:        "AAPL", "SPY"
  - Indian NSE stocks:     "RELIANCE.NS", "TCS.NS"
  - Indian BSE stocks:     "RELIANCE.BO"

Responsibilities:
  - Live/last price + volume
  - OHLC historical candles
  - Basic indicators (SMA, EMA, RSI) computed from candles
  - Order book: yfinance does not provide L2 order book data (it's not
    publicly available for free). This is exposed as `get_orderbook()`
    returning None with a clear capability note, rather than silently
    faking data. If you later get a brokered API with order book access,
    plug it in behind the same interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class Quote:
    symbol: str
    price: float
    volume: int
    timestamp: datetime
    change_pct: Optional[float] = None


class MarketAPIError(Exception):
    pass


class MarketDataClient:
    """Thin, swappable wrapper around yfinance.

    Keeping this as its own class (rather than calling yfinance directly
    all over the codebase) means we can later swap in a paid/realtime feed
    (Polygon, broker API, etc.) without touching the Signal Engine or
    Recommendation Engine.
    """

    def __init__(self, default_interval: str = "1m"):
        self.default_interval = default_interval

    # ---------- Live quote ----------

    def get_quote(self, symbol: str) -> Quote:
        ticker = yf.Ticker(symbol)
        try:
            fast = ticker.fast_info
            price = float(fast["lastPrice"])
            volume = int(fast.get("lastVolume") or 0)
            prev_close = fast.get("previousClose")
            change_pct = (
                round((price - prev_close) / prev_close * 100, 3)
                if prev_close
                else None
            )
            return Quote(
                symbol=symbol,
                price=price,
                volume=volume,
                timestamp=datetime.now(),
                change_pct=change_pct,
            )
        except Exception as exc:
            raise MarketAPIError(f"Failed to fetch quote for {symbol}: {exc}") from exc

    # ---------- Historical candles ----------

    def get_candles(
        self, symbol: str, period: str = "5d", interval: str = "5m"
    ) -> pd.DataFrame:
        """Returns OHLCV dataframe indexed by datetime.

        period: e.g. '1d','5d','1mo','6mo','1y','5y','max'
        interval: e.g. '1m','5m','15m','1h','1d' (1m only available for period<=7d)
        """
        df = yf.Ticker(symbol).history(period=period, interval=interval)
        if df.empty:
            raise MarketAPIError(f"No candle data returned for {symbol}")
        df = df.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            }
        )
        return df[["open", "high", "low", "close", "volume"]]

    # ---------- Indicators ----------

    def with_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Adds SMA20, SMA50, EMA20, RSI14 columns to a candle dataframe."""
        out = df.copy()
        out["sma20"] = out["close"].rolling(20).mean()
        out["sma50"] = out["close"].rolling(50).mean()
        out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
        out["rsi14"] = self._rsi(out["close"], 14)
        return out

    @staticmethod
    def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()

        rsi = pd.Series(index=series.index, dtype="float64")
        has_window = avg_gain.notna() & avg_loss.notna()

        # Standard case: both avg_gain and avg_loss are non-zero -> normal RS formula
        normal = has_window & (avg_loss != 0)
        rs = avg_gain[normal] / avg_loss[normal]
        rsi[normal] = 100 - (100 / (1 + rs))

        # Edge case: no losses in the window at all -> maximally overbought (100)
        no_loss = has_window & (avg_loss == 0) & (avg_gain > 0)
        rsi[no_loss] = 100.0

        # Edge case: no gains and no losses (flat price) -> neutral midpoint
        flat = has_window & (avg_loss == 0) & (avg_gain == 0)
        rsi[flat] = 50.0

        return rsi

    # ---------- Order book (capability-limited) ----------

    def get_orderbook(self, symbol: str) -> Optional[dict]:
        """yfinance does not expose Level-2 order book data.

        Returns None. Calling code must handle this gracefully — do not
        treat None as "all zeros" or synthesize fake depth.
        """
        logger.info(
            "Order book requested for %s but free data source has no L2 depth.",
            symbol,
        )
        return None
