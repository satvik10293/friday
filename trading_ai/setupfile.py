"""
rebuild_trading_ai.py — one-shot installer for the Screen-Aware Trading
Assistant.

Run this once from inside your tarding_ai/ project folder. It will:

  1. Delete the current project source files (NOT your data — trading_assistant.db,
     region_finder.png, .venv, and anything not listed below are left alone).
  2. Write out the full rebuilt set of files: Phase 1 (market data + screen
     vision) + Phase 3 (recommendation engine + voice alerts) + main.py,
     all using the flat-file import layout this project already uses.

Usage:
    python rebuild_trading_ai.py

Then:
    python -m pip install -r requirements.txt
    pytest -m "not network"
    python main.py --symbol AAPL
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── SAFETY INTERLOCK ─────────────────────────────────────────────────────────
# This script DELETES the project's source files and rewrites them from the
# copies embedded below — copies frozen on 2026-06-21, OLDER than the current
# modules. Running it casually would silently regress every file edited since
# (this exact class of accident once overwrote a FRIDAY module with a setup
# script). It refuses to run unless you explicitly opt in:
#
#     set TRADING_AI_REBUILD_CONFIRM=yes && python setupfile.py
#
if __name__ == "__main__" and os.environ.get("TRADING_AI_REBUILD_CONFIRM") != "yes":
    sys.exit(
        "REFUSING to run: this rebuilder would OVERWRITE the current project "
        "source with stale 2026-06-21 copies embedded in this file.\n"
        "If you really mean it, set TRADING_AI_REBUILD_CONFIRM=yes and re-run."
    )

PROJECT_DIR = Path(__file__).resolve().parent

DELETE_FILES = [
    "README.md",
    "data_db.py",
    "data_init.py",
    "data_market_api.py",
    "find_region.py",
    "journal_init.py",
    "journal_trade_journal.py",
    "learning_action_logger.py",
    "learning_init.py",
    "learning_strategy_scorer.py",
    "main.py",
    "output_voice_alert.py",
    "pytest.ini",
    "recommend_init.py",
    "recommend_recommendation_engine.py",
    "requirements.txt",
    "signals_init.py",
    "signals_signal_engine.py",
    "tests_test_db.py",
    "tests_test_market_api.py",
    "tests_test_ocr_reader.py",
    "tests_test_screen_capture.py",
    "vision_chart_detector.py",
    "vision_init.py",
    "vision_ocr_reader.py",
    "vision_position_tracker.py",
    "vision_screen_capture.py",
    "vision_ui_detector.py",
]

FILES: dict[str, str] = {}

FILES['README.md'] = r'''# Screen-Aware Trading Assistant

A local, **observe-and-recommend-only** desktop assistant. It watches market
data + your trading screen, learns from your demo-account actions, and
speaks BUY / SELL / HOLD / WAIT calls out loud with its reasons. **It never
places trades, enters credentials, or clicks anything.**

This is a flat-file layout (all modules live directly in this folder, no
subfolders) — matching the `tarding_ai` project structure on your machine.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1 | Screen capture, OCR, Market API integration | Done, tested |
| 2 | Technical indicators, chart pattern recognition | Indicators done in `data_market_api.py`; candlestick/breakout detection in `vision_chart_detector.py` still a placeholder |
| 3 | Recommendation engine | Done — `recommend_recommendation_engine.py` |
| 3.5 | Voice output | Done — `output_voice_alert.py`, wired into `main.py` |
| 4 | Learning engine | Scoring storage exists in `data_db.py`; standalone `learning_*` modules still placeholders |
| 5 | Streamlit dashboard | Not started |
| 6 | Backtesting | Not started |

## Files

```
main.py                          — entry point, run this
find_region.py                   — one-off helper to find --region coordinates

data_market_api.py               — yfinance wrapper: quotes, OHLCV, SMA/EMA/RSI
data_db.py                       — SQLite: candles, user_actions, trade_journal, strategy_scores

vision_screen_capture.py         — periodic screenshots via mss (read-only)
vision_ocr_reader.py             — EasyOCR + regex parser (prices/symbols/P&L)
vision_chart_detector.py         — Phase 2 placeholder
vision_ui_detector.py            — Phase 2 placeholder
vision_position_tracker.py       — Phase 2 placeholder

recommend_recommendation_engine.py — combines indicators + learning history into BUY/SELL/HOLD/WAIT + reasons
output_voice_alert.py            — speaks recommendations aloud (pyttsx3, offline TTS)

learning_action_logger.py        — Phase 4 placeholder
learning_strategy_scorer.py      — Phase 4 placeholder
journal_trade_journal.py         — Phase 4 placeholder (open_trade/close_trade already live in data_db.py)
signals_signal_engine.py         — Phase 2/4 placeholder

tests_test_*.py                  — 24 tests; run with pytest
```

## Setup (Windows / PyCharm)

Always call pip through your interpreter explicitly — never the bare `pip`
command, which can point at a stale launcher:

```powershell
cd trading_ai
python -m pip install -r requirements.txt
```

`easyocr` pulls in `torch` — first install is large (~1-2 GB) and the first
`OCRReader.reader` access downloads detection/recognition models, which
needs real internet access (this won't work in a sandboxed/offline
environment).

Run the offline test suite:

```powershell
pytest -m "not network"
```

## Running it

```powershell
python main.py --symbol AAPL
```

What it does each cycle (every `--interval` seconds, default 3):
- Pulls a live quote (Eye 1)
- Captures your screen and OCRs it (Eye 2) — unless `--no-screen`
- Every `--rec-interval` seconds (default 60s, to avoid hammering Yahoo
  Finance), evaluates a BUY/SELL/HOLD/WAIT recommendation, prints it,
  logs it to `user_actions`, and speaks it aloud — unless `--no-voice`

Common flags:

```powershell
# Watch just market data, no screen capture
python main.py --symbol AAPL --no-screen

# Point screen capture at your trading platform window instead of the whole screen
python find_region.py
# open region_finder.png, read off the coordinates, then:
python main.py --symbol AAPL --region LEFT,TOP,WIDTH,HEIGHT

# Silence voice, console output only
python main.py --symbol AAPL --no-voice

# Tell it you already have an open position (changes BUY/SELL semantics)
python main.py --symbol AAPL --has-position

# Indian markets
python main.py --symbol RELIANCE.NS
```

Stop any time with `Ctrl+C` — it shuts down cleanly.

## Design notes / decisions

- **Order book**: yfinance has no free Level-2 depth. `get_orderbook()`
  returns `None` rather than fake data.
- **OCR parsing is regex-based for now.** It can't yet tell "this is the
  LTP" from "this is yesterday's high" — that needs `read_with_boxes()`
  (already implemented) paired with `ui_detector.py` mapped to your actual
  platform's layout. Still a Phase 2 task.
- **RSI** handles zero-loss/zero-gain edge cases explicitly (pure uptrend
  → 100, flat price → 50) instead of producing NaN.
- **Recommendation confidence** is a hand-weighted heuristic (trend +
  RSI + volume + historical win rate from `strategy_scores`), not a
  trained model. Phase 4's learning engine is meant to replace these fixed
  weights with values learned from real win/loss history.
- **Recommendations are throttled** to `--rec-interval` seconds (default
  60), separate from the faster `--interval` observe cycle, because
  `get_candles()` is a real network call to Yahoo Finance — calling it
  every 3 seconds would be wasteful and risks rate-limiting.
- **Voice alerts deduplicate**: the same action for the same symbol won't
  be re-spoken within 30 seconds, so it doesn't repeat itself every cycle
  while the signal hasn't changed.

## Safety rules (enforced by design, not just by policy)

- No module in this codebase sends mouse/keyboard input. There is no
  click-automation library imported anywhere.
- No credential fields, no broker login flow, no order-placement API calls
  exist in this codebase.
- `get_orderbook()` and any future broker-API integration must keep
  observe-only semantics — read endpoints (quotes/positions) only, never
  order-entry endpoints.

## Next step

Phase 2: candlestick/breakout/support-resistance detection in
`vision_chart_detector.py`, plus wiring `vision_ui_detector.py` to your
actual platform layout (you're using TradingView Paper Trading — send a
fresh screenshot if you want region templates built for its specific
panel layout instead of generic regex parsing).
'''

FILES['data_db.py'] = r'''"""
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
'''

FILES['data_market_api.py'] = r'''"""
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
'''

FILES['find_region.py'] = r'''"""
find_region.py — one-off utility to help you pick --region LEFT,TOP,WIDTH,HEIGHT
for main.py.

Run this with your trading platform window visible on screen. It saves
region_finder.png: your screen with a green coordinate grid drawn every
100px so you can read off the top-left corner and size of the window you
want main.py to watch.

This only reads pixels (same as vision_screen_capture.py) — it never
clicks or sends input anywhere.
"""

from __future__ import annotations

import cv2
import mss
import numpy as np


def grab_full_screen() -> tuple[np.ndarray, list[dict]]:
    with mss.mss() as sct:
        monitors = sct.monitors
        print("Detected monitors:")
        for i, m in enumerate(monitors):
            print(f"  [{i}] {m}")

        # monitors[0] is the "all monitors combined" virtual screen; grab that
        # so the grid covers everything, including secondary monitors.
        raw = sct.grab(monitors[0])
        img = np.array(raw)[:, :, :3]  # drop alpha
        return img, monitors


def draw_grid(img: np.ndarray, step: int = 100) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    color = (0, 255, 0)  # green, BGR
    thickness = 1
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.4

    for x in range(0, w, step):
        cv2.line(out, (x, 0), (x, h), color, thickness)
        cv2.putText(out, str(x), (x + 3, 15), font, font_scale, color, 1, cv2.LINE_AA)

    for y in range(0, h, step):
        cv2.line(out, (0, y), (w, y), color, thickness)
        cv2.putText(out, str(y), (3, y + 12), font, font_scale, color, 1, cv2.LINE_AA)

    return out


def main() -> None:
    img, _monitors = grab_full_screen()
    gridded = draw_grid(img)

    out_path = "region_finder.png"
    cv2.imwrite(out_path, gridded)

    print(f"Saved {out_path} — open it, find your trading platform window,")
    print("and read off left/top (top-left corner) and width/height from the grid.")
    print("Then run:  python main.py --symbol AAPL --region LEFT,TOP,WIDTH,HEIGHT")


if __name__ == "__main__":
    main()
'''

FILES['journal_trade_journal.py'] = r'''"""Placeholder — implemented in a later phase per project roadmap."""
'''

FILES['learning_action_logger.py'] = r'''"""Placeholder — implemented in a later phase per project roadmap."""
'''

FILES['learning_strategy_scorer.py'] = r'''"""Placeholder — implemented in a later phase per project roadmap."""
'''

FILES['main.py'] = r'''"""
main.py — Screen-Aware Trading Assistant entry point.

Wires together everything built so far into one running loop:

  Eye 1 (data_market_api)      -> live quote every cycle
  Eye 2 (vision_screen_capture
         + vision_ocr_reader)  -> screen capture + OCR every cycle (optional)
  Recommendation Engine        -> BUY/SELL/HOLD/WAIT every N seconds
  Voice Alert                  -> speaks the recommendation aloud (optional)
  Database                     -> logs every recommendation as a user_action

SAFETY: this script only reads pixels and reads market data. It never
clicks, types, or sends input anywhere, and never places real trades.
Per the project spec, it observes and recommends only.

Usage:
  python main.py --symbol AAPL
  python main.py --symbol RELIANCE.NS --region 790,0,810,860
  python main.py --symbol AAPL --no-screen          (market data only)
  python main.py --symbol AAPL --no-voice           (silent, console only)
  python main.py --symbol AAPL --has-position        (you're already in a trade)
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from data_db import Database
from data_market_api import MarketAPIError, MarketDataClient
from recommend_recommendation_engine import RecommendationEngine


def parse_region(value: Optional[str]) -> Optional[dict]:
    """Parses '--region LEFT,TOP,WIDTH,HEIGHT' into the dict ScreenCapture expects."""
    if not value:
        return None
    try:
        left, top, width, height = (int(p.strip()) for p in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "--region must be 4 comma-separated integers: LEFT,TOP,WIDTH,HEIGHT"
        ) from exc
    return {"left": left, "top": top, "width": width, "height": height}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Screen-Aware Trading Assistant (observe-only)")
    parser.add_argument("--symbol", default="AAPL", help="Ticker to watch (e.g. AAPL, RELIANCE.NS)")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between observe cycles (1-5s recommended)")
    parser.add_argument("--region", type=str, default=None, help="Screen region to capture: LEFT,TOP,WIDTH,HEIGHT (default: full primary monitor)")
    parser.add_argument("--monitor-index", type=int, default=1, help="Which monitor to capture when --region is not set (mss numbering, 1=primary)")
    parser.add_argument("--no-screen", action="store_true", help="Skip screen capture + OCR entirely (market data only)")
    parser.add_argument("--no-voice", action="store_true", help="Disable spoken voice alerts (console/log only)")
    parser.add_argument("--gpu", action="store_true", help="Use GPU for OCR if available (default: CPU)")
    parser.add_argument("--rec-interval", type=float, default=60.0, help="Seconds between recommendation evaluations (default 60s, keeps yfinance calls reasonable)")
    parser.add_argument("--has-position", action="store_true", help="Tell the engine you currently have an open position (changes BUY/SELL -> HOLD/SELL semantics)")
    parser.add_argument("--setup-tag", default="trend_continuation", help="Strategy/setup label used for learning-engine lookups and trade journal tagging")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    region = parse_region(args.region)

    market = MarketDataClient()
    db = Database()
    engine = RecommendationEngine(market=market, db=db)

    screen_capture = None
    ocr_reader = None
    if not args.no_screen:
        from vision_screen_capture import ScreenCapture
        from vision_ocr_reader import OCRReader

        screen_capture = ScreenCapture(monitor_index=args.monitor_index, region=region)
        ocr_reader = OCRReader(gpu=args.gpu)

    voice = None
    if not args.no_voice:
        try:
            from output_voice_alert import VoiceAlert

            voice = VoiceAlert()
        except ImportError as exc:
            print(f"[WARN] Voice alerts disabled — {exc}")

    print(f"Watching {args.symbol} | cycle every {args.interval}s | "
          f"recommendations every {args.rec_interval}s | Ctrl+C to stop")
    if not args.no_screen and ocr_reader is not None:
        print("Loading OCR engine (first run downloads models, can take a minute)...")

    cycle = 0
    last_rec_time = 0.0

    try:
        while True:
            cycle += 1
            print(f"--- Cycle {cycle} ---")

            # ---- Eye 1: market data ----
            quote = None
            try:
                quote = market.get_quote(args.symbol)
                arrow = "Δ" if quote.change_pct is None else f"Δ {quote.change_pct:+.3f}%"
                print(f"[Market]  {quote.symbol}: {quote.price}  ({arrow})  vol={quote.volume}")
            except MarketAPIError as exc:
                print(f"[Market]  error: {exc}")

            # ---- Eye 2: screen vision (optional) ----
            if screen_capture is not None and ocr_reader is not None:
                try:
                    frame = screen_capture.capture_once()
                    result = ocr_reader.read_and_parse(frame.image)
                    print(f"[Screen]  symbols={result.symbols}  prices={result.prices}  pnl={result.pnl_candidates}")
                except Exception as exc:  # vision is best-effort; never crash the loop over it
                    print(f"[Screen]  error: {exc}")

            # ---- Recommendation engine, throttled to --rec-interval ----
            now = time.time()
            if quote is not None and (now - last_rec_time) >= args.rec_interval:
                last_rec_time = now
                rec = engine.evaluate(
                    args.symbol,
                    has_open_position=args.has_position,
                    setup_tag=args.setup_tag,
                )
                print(f"[Recommend]\n{rec}")

                db.log_action(
                    symbol=rec.symbol,
                    action=rec.action,
                    price=quote.price,
                    reason="; ".join(rec.reasons),
                    source="recommendation",
                )

                if voice is not None:
                    voice.announce(rec)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if voice is not None:
            voice.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

FILES['output_voice_alert.py'] = r'''"""
Output Module — Voice Alerts.

Takes a Recommendation (from recommend_recommendation_engine.py) and speaks
it out loud: action, confidence, and the reasons behind it. Also prints the
same thing to console so nothing is lost if speakers are muted/unavailable.

Strictly observe-and-announce, in line with the project's safety rules:
this module NEVER clicks anything, places anything, or touches the trading
platform. It only converts a Recommendation object into speech/text.

Uses pyttsx3 (offline, no API key, works without internet) so it keeps the
same "no external dependency beyond pip install" philosophy as the rest of
the project.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional

try:
    import pyttsx3
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "pyttsx3 is required for voice alerts. Install it with:\n"
        "    pip install pyttsx3\n"
        "On Windows this uses SAPI5 and needs no extra setup."
    ) from exc

from recommend_recommendation_engine import Recommendation


@dataclass
class VoiceSettings:
    rate: int = 175          # words per minute
    volume: float = 1.0      # 0.0 - 1.0
    voice_index: Optional[int] = None  # None = engine default voice
    min_seconds_between_repeats: float = 30.0  # don't re-announce the same call too often


class VoiceAlert:
    """
    Wraps pyttsx3 in a background thread so speaking never blocks the main
    observe/analyze loop in main.py. Recommendations are queued and spoken
    one at a time, in order.
    """

    def __init__(self, settings: Optional[VoiceSettings] = None):
        self.settings = settings or VoiceSettings()
        self._queue: "queue.Queue[Recommendation]" = queue.Queue()
        self._last_announced = {}  # symbol -> (action, timestamp)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    # ---- public API -----------------------------------------------------

    def announce(self, rec: Recommendation, force: bool = False) -> None:
        """
        Queue a recommendation to be spoken. By default, suppresses repeat
        announcements of the same action for the same symbol within
        min_seconds_between_repeats, so it doesn't nag every cycle while a
        signal stays unchanged.
        """
        key = rec.symbol
        now = time.time()
        last = self._last_announced.get(key)

        if not force and last is not None:
            last_action, last_time = last
            same_call = last_action == rec.action
            too_soon = (now - last_time) < self.settings.min_seconds_between_repeats
            if same_call and too_soon:
                return

        self._last_announced[key] = (rec.action, now)
        self._queue.put(rec)

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(None)  # unblock the worker thread
        self._thread.join(timeout=5)

    # ---- internals --------------------------------------------------------

    def _build_speech_text(self, rec: Recommendation) -> str:
        action_phrase = {
            "BUY": "Buy signal",
            "SELL": "Sell signal",
            "HOLD": "Hold",
            "WAIT": "Wait, no clear setup",
        }.get(rec.action, rec.action)

        parts = [f"{action_phrase} on {rec.symbol}.", f"Confidence {rec.confidence:.0f} percent."]

        if rec.reasons:
            parts.append("Reasons:")
            for reason in rec.reasons:
                parts.append(reason)

        return " ".join(parts)

    def _run(self) -> None:
        engine = pyttsx3.init()
        engine.setProperty("rate", self.settings.rate)
        engine.setProperty("volume", self.settings.volume)

        if self.settings.voice_index is not None:
            voices = engine.getProperty("voices")
            if 0 <= self.settings.voice_index < len(voices):
                engine.setProperty("voice", voices[self.settings.voice_index].id)

        while not self._stop_event.is_set():
            rec = self._queue.get()
            if rec is None:
                break

            text = self._build_speech_text(rec)
            print(f"\n[VOICE ALERT] {text}\n")

            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:  # pragma: no cover - hardware/driver dependent
                print(f"[VOICE ALERT] (speech failed, text-only) {exc}")


# ---- quick manual test -----------------------------------------------------

if __name__ == "__main__":
    sample = Recommendation(
        symbol="AAPL",
        action="BUY",
        confidence=81.0,
        reasons=[
            "Uptrend confirmed (price > SMA20 > SMA50)",
            "Volume increasing vs recent average",
            "Similar trend_continuation setup won 14 of last 20 times",
        ],
    )

    alert = VoiceAlert()
    alert.announce(sample, force=True)
    time.sleep(6)  # give the background thread time to actually speak
    alert.stop()
'''

FILES['pytest.ini'] = r'''[pytest]
markers =
    network: tests that require live internet access to real market data APIs
python_files = test_*.py tests_test_*.py
'''

FILES['recommend_recommendation_engine.py'] = r'''"""
Phase 3 — Recommendation Engine.

Combines market data (Eye 1: candles + indicators) with whatever the
Learning Engine has scored so far (strategy_scores table) into a single
recommendation: BUY / SELL / HOLD / WAIT, with a confidence score and a
list of human-readable reasons.

Design notes:
- This intentionally does NOT use noisy OCR/screen data as a primary
  signal input yet. Screen vision (Eye 2) is still Phase 1/2-quality —
  good enough to log what's on screen, not reliable enough to drive a
  buy/sell call. Once chart_detector.py (breakout/support/resistance
  detection) is built in Phase 2, that becomes a real input here.
- "WAIT" is distinct from "HOLD": HOLD means "you have a position, stay
  in it"; WAIT means "no position, no clear setup, don't enter."
- Confidence is a simple weighted heuristic score for now, not a trained
  model — that upgrade path belongs to the Learning Engine (Phase 4),
  which will eventually replace these fixed weights with values learned
  from win/loss history per setup_tag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

from data_db import Database
from data_market_api import MarketAPIError, MarketDataClient


@dataclass
class Recommendation:
    symbol: str
    action: str  # BUY, SELL, HOLD, WAIT
    confidence: float  # 0-100
    reasons: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"{self.action} SIGNAL — {self.symbol}", f"Confidence: {self.confidence:.0f}%"]
        for r in self.reasons:
            lines.append(f"  - {r}")
        return "\n".join(lines)


class RecommendationEngine:
    def __init__(self, market: Optional[MarketDataClient] = None, db: Optional[Database] = None):
        self.market = market or MarketDataClient()
        self.db = db or Database()

    def evaluate(
        self, symbol: str, has_open_position: bool = False, setup_tag: str = "trend_continuation"
    ) -> Recommendation:
        try:
            candles = self.market.get_candles(symbol, period="5d", interval="15m")
        except MarketAPIError as exc:
            return Recommendation(symbol, "WAIT", 0.0, [f"Could not fetch data: {exc}"])

        df = self.market.with_indicators(candles)
        return self._evaluate_from_indicators(df, symbol, has_open_position, setup_tag)

    def _evaluate_from_indicators(
        self, df: pd.DataFrame, symbol: str, has_open_position: bool, setup_tag: str
    ) -> Recommendation:
        if len(df) < 50 or df[["sma20", "sma50", "rsi14"]].iloc[-1].isna().any():
            return Recommendation(symbol, "WAIT", 0.0, ["Not enough history yet for reliable indicators"])

        last = df.iloc[-1]
        prev = df.iloc[-2]

        score = 0.0
        reasons: List[str] = []

        # Trend: price above both moving averages, and sma20 above sma50
        bullish_trend = last.close > last.sma20 > last.sma50
        bearish_trend = last.close < last.sma20 < last.sma50
        if bullish_trend:
            score += 30
            reasons.append("Uptrend confirmed (price > SMA20 > SMA50)")
        elif bearish_trend:
            score -= 30
            reasons.append("Downtrend confirmed (price < SMA20 < SMA50)")

        # Momentum via RSI
        if last.rsi14 < 30:
            score += 20
            reasons.append(f"RSI oversold ({last.rsi14:.1f}) — potential bounce")
        elif last.rsi14 > 70:
            score -= 20
            reasons.append(f"RSI overbought ({last.rsi14:.1f}) — potential pullback")

        # Volume trend: is volume picking up vs the recent average?
        recent_avg_vol = df["volume"].iloc[-10:-1].mean()
        if recent_avg_vol and last.volume > recent_avg_vol * 1.3:
            score += 15 if score >= 0 else -15
            reasons.append("Volume increasing vs recent average")

        # Momentum confirmation: last candle closed higher/lower than previous
        if last.close > prev.close and bullish_trend:
            score += 10
            reasons.append("Last candle closed higher, confirming move")
        elif last.close < prev.close and bearish_trend:
            score -= 10
            reasons.append("Last candle closed lower, confirming move")

        # Learning Engine input: has this setup historically won?
        history = self.db.get_strategy_score(setup_tag)
        if history and (history["wins"] + history["losses"]) >= 5:
            win_rate = history["confidence"]
            total = history["wins"] + history["losses"]
            reasons.append(
                f"Similar '{setup_tag}' setup won {history['wins']} of last {total} times"
            )
            # Nudge score toward/away from the signal based on historical win rate
            score *= 0.5 + win_rate  # win_rate 0->halves score, 1->1.5x score

        confidence = min(100.0, abs(score))
        if score >= 40:
            action = "HOLD" if has_open_position else "BUY"
        elif score <= -40:
            action = "SELL" if has_open_position else "WAIT"
        else:
            action = "HOLD" if has_open_position else "WAIT"
            if not reasons:
                reasons.append("No clear setup — indicators are mixed or flat")

        return Recommendation(symbol, action, confidence, reasons)
'''

FILES['requirements.txt'] = r'''## Phase 1 (implemented now)
yfinance>=0.2.40
pandas>=2.0
mss>=9.0.1
opencv-python-headless>=4.9
numpy>=1.26
easyocr>=1.7.1
pytest>=8.0

## Phase 3 (implemented now)
pyttsx3>=2.90        # offline text-to-speech for voice alerts

## Phase 2/4/5 (install when you reach that phase)
# streamlit>=1.35        # Dashboard
# scikit-learn>=1.4      # Strategy scoring / pattern learning
'''

FILES['signals_signal_engine.py'] = r'''"""Placeholder — implemented in a later phase per project roadmap."""
'''

FILES['tests_test_db.py'] = r'''import sqlite3
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
'''

FILES['tests_test_market_api.py'] = r'''"""
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
'''

FILES['tests_test_ocr_reader.py'] = r'''from vision_ocr_reader import OCRReader


def test_parse_extracts_prices_and_symbols():
    reader = OCRReader()
    raw = ["AAPL", "182.45", "Volume: 23,451,200", "RELIANCE.NS", "2,845.10"]
    result = reader.parse(raw)
    assert "AAPL" in result.symbols
    assert 182.45 in result.prices
    assert 2845.10 in result.prices


def test_parse_detects_pnl_candidates():
    reader = OCRReader()
    raw = ["P&L: +$245.30", "Position: LONG 100 shares", "+2.4%"]
    result = reader.parse(raw)
    assert any("245.30" in c for c in result.pnl_candidates)
    assert "+2.4%" in result.pnl_candidates


def test_parse_handles_empty_and_garbage_strings():
    reader = OCRReader()
    raw = ["", "   ", "###", "----"]
    result = reader.parse(raw)
    assert result.prices == []
    assert result.symbols == []


def test_parse_does_not_crash_on_malformed_numbers():
    reader = OCRReader()
    raw = ["..", "-.", "1..2.3"]
    result = reader.parse(raw)  # should not raise
    assert isinstance(result.prices, list)
'''

FILES['tests_test_screen_capture.py'] = r'''from unittest.mock import MagicMock, patch

import numpy as np

from vision_screen_capture import ScreenCapture


def _fake_mss(monitor_shape=(100, 200, 4)):
    """Builds a mock mss.mss() context manager returning a fake screenshot."""
    fake_sct = MagicMock()
    fake_sct.monitors = [
        {"top": 0, "left": 0, "width": 1, "height": 1},  # index 0: "all"
        {"top": 0, "left": 0, "width": 200, "height": 100},  # index 1: primary
    ]
    fake_sct.grab.return_value = np.zeros(monitor_shape, dtype=np.uint8)
    cm = MagicMock()
    cm.__enter__.return_value = fake_sct
    cm.__exit__.return_value = False
    return cm


def test_capture_once_returns_frame_with_correct_shape():
    with patch("vision_screen_capture.mss.mss", return_value=_fake_mss()):
        cap = ScreenCapture(monitor_index=1)
        frame = cap.capture_once()
    assert frame.image.shape == (100, 200, 3)  # alpha channel dropped
    assert frame.monitor_index == 1


def test_capture_once_uses_custom_region():
    region = {"top": 10, "left": 10, "width": 50, "height": 50}
    with patch(
        "vision_screen_capture.mss.mss", return_value=_fake_mss((50, 50, 4))
    ) as mock_mss:
        cap = ScreenCapture(region=region)
        cap.capture_once()
    grabbed_arg = mock_mss.return_value.__enter__.return_value.grab.call_args[0][0]
    assert grabbed_arg == region


def test_stream_yields_max_frames_and_calls_callback():
    received = []
    with patch("vision_screen_capture.mss.mss", return_value=_fake_mss()):
        with patch("vision_screen_capture.time.sleep", return_value=None):
            cap = ScreenCapture(monitor_index=1)
            frames = list(
                cap.stream(interval_seconds=0, on_frame=received.append, max_frames=3)
            )
    assert len(frames) == 3
    assert len(received) == 3
'''

FILES['vision_chart_detector.py'] = r'''"""
PHASE 2 MODULE — not yet implemented.

This file is a placeholder so the package structure/imports work end-to-end
from Phase 1. Implement in Phase 2 per the dev order in the spec.
"""
'''

FILES['vision_ocr_reader.py'] = r'''"""
Eye 2, Stage 2 — OCR Reader.

Extracts text (prices, symbols, indicator values, P&L, position details)
from a captured Frame using EasyOCR, then parses that raw text into
structured fields with regex.

Lazy-loads EasyOCR's Reader because model loading is slow (~seconds) and
pulls in torch — we don't want that cost paid by code that just imports
this module for type hints or tests with a mocked reader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

_PRICE_RE = re.compile(r"[-+]?\d{1,3}(?:[,\d]{0,10})?\.?\d{0,4}")
_SYMBOL_RE = re.compile(r"\b[A-Z]{2,10}(?:\.[A-Z]{2})?\b")
_PNL_RE = re.compile(r"[-+]?\$?\s?\d[\d,]*\.?\d*\s?%?")


@dataclass
class OCRResult:
    raw_text: List[str]
    prices: List[float] = field(default_factory=list)
    symbols: List[str] = field(default_factory=list)
    pnl_candidates: List[str] = field(default_factory=list)


class OCRReader:
    def __init__(self, languages: Optional[List[str]] = None, gpu: bool = False):
        self.languages = languages or ["en"]
        self.gpu = gpu
        self._reader = None  # lazy

    @property
    def reader(self):
        if self._reader is None:
            import easyocr  # heavy import, deferred

            self._reader = easyocr.Reader(self.languages, gpu=self.gpu)
        return self._reader

    def read_text(self, image: np.ndarray) -> List[str]:
        """Returns raw recognized text strings (no positions) from an image."""
        results = self.reader.readtext(image, detail=0)
        return list(results)

    def read_with_boxes(self, image: np.ndarray):
        """Returns [(box, text, confidence), ...] — useful for ui_detector.py
        to know *where* on screen a price/label sits, not just that it exists.
        """
        return self.reader.readtext(image, detail=1)

    def parse(self, raw_text: List[str]) -> OCRResult:
        """Heuristic structured parse of raw OCR strings.

        This is intentionally simple/regex-based for Phase 1. Phase 2+ should
        replace blind regex matching with positional parsing (read_with_boxes)
        so e.g. "the number under the LTP label" is reliably the price, not
        just "some number-looking string on screen".
        """
        prices: List[float] = []
        symbols: List[str] = []
        pnl_candidates: List[str] = []

        for text in raw_text:
            cleaned = text.strip()
            if not cleaned:
                continue

            sym_matches = _SYMBOL_RE.findall(cleaned)
            symbols.extend(sym_matches)

            if any(c.isdigit() for c in cleaned):
                price_matches = _PRICE_RE.findall(cleaned)
                for p in price_matches:
                    p_clean = p.replace(",", "")
                    try:
                        if p_clean and p_clean not in (".", "-", "+"):
                            prices.append(float(p_clean))
                    except ValueError:
                        continue

            if "%" in cleaned or "$" in cleaned or cleaned.lower().startswith(("p&l", "pnl")):
                pnl_candidates.append(cleaned)

        return OCRResult(
            raw_text=raw_text,
            prices=prices,
            symbols=symbols,
            pnl_candidates=pnl_candidates,
        )

    def read_and_parse(self, image: np.ndarray) -> OCRResult:
        return self.parse(self.read_text(image))
'''

FILES['vision_position_tracker.py'] = r'''"""
PHASE 2 MODULE — not yet implemented.

This file is a placeholder so the package structure/imports work end-to-end
from Phase 1. Implement in Phase 2 per the dev order in the spec.
"""
'''

FILES['vision_screen_capture.py'] = r'''"""
Eye 2, Stage 1 — Screen Capture.

Captures the screen (or a specific monitor/region) on an interval and hands
frames to downstream modules (OCR, chart detection, UI detection).

Uses `mss` (fast, cross-platform, no GUI deps) rather than pyautogui's
screenshot, which is slower for repeated capture.

Safety note: this module ONLY reads pixels. It never sends input
(no click/keyboard) — see vision/ui_detector.py and the project safety
rules: this app observes, it does not act on the screen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import mss
import numpy as np


@dataclass
class Frame:
    image: np.ndarray  # BGR, shape (H, W, 3)
    timestamp: datetime
    monitor_index: int


class ScreenCapture:
    def __init__(self, monitor_index: int = 1, region: Optional[dict] = None):
        """
        monitor_index: which monitor to capture (1 = primary in mss's numbering;
                        0 means "all monitors combined", which we avoid by default).
        region: optional dict {"top":..,"left":..,"width":..,"height":..} to
                 capture only the trading-platform window area instead of the
                 full screen. Narrowing this improves OCR speed/accuracy.
        """
        self.monitor_index = monitor_index
        self.region = region

    def capture_once(self) -> Frame:
        with mss.mss() as sct:
            target = self.region or sct.monitors[self.monitor_index]
            raw = sct.grab(target)
            img = np.array(raw)[:, :, :3]  # drop alpha, keep BGR-ish order
            return Frame(image=img, timestamp=datetime.now(), monitor_index=self.monitor_index)

    def stream(
        self,
        interval_seconds: float = 2.0,
        on_frame: Optional[Callable[[Frame], None]] = None,
        max_frames: Optional[int] = None,
    ):
        """Generator yielding Frame objects every `interval_seconds`.

        interval_seconds: keep within the spec's 1-5s range. Lower values cost
        more CPU (OCR + CV downstream); 2-3s is a reasonable default for a
        trading dashboard that isn't scalping tick-by-tick.
        """
        count = 0
        while max_frames is None or count < max_frames:
            frame = self.capture_once()
            if on_frame:
                on_frame(frame)
            yield frame
            count += 1
            time.sleep(interval_seconds)

    @staticmethod
    def save_frame(frame: Frame, out_dir: Path) -> Path:
        import cv2

        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"screen_{frame.timestamp.strftime('%Y%m%d_%H%M%S_%f')}.png"
        cv2.imwrite(str(path), frame.image)
        return path
'''

FILES['vision_ui_detector.py'] = r'''"""
PHASE 2 MODULE — not yet implemented.

This file is a placeholder so the package structure/imports work end-to-end
from Phase 1. Implement in Phase 2 per the dev order in the spec.
"""
'''



def main() -> None:
    print(f"Rebuilding trading assistant project in: {PROJECT_DIR}\n")

    deleted = 0
    for name in DELETE_FILES:
        path = PROJECT_DIR / name
        if path.exists():
            path.unlink()
            deleted += 1
            print(f"  deleted  {name}")
    print(f"\n{deleted} old file(s) removed.\n")

    written = 0
    for name, content in sorted(FILES.items()):
        path = PROJECT_DIR / name
        path.write_text(content, encoding="utf-8")
        written += 1
        print(f"  wrote    {name}")
    print(f"\n{written} file(s) written.\n")

    print("Done. Next steps:")
    print("  python -m pip install -r requirements.txt")
    print('  pytest -m "not network"')
    print("  python main.py --symbol AAPL")


if __name__ == "__main__":
    main()