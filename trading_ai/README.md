# Screen-Aware Trading Assistant

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
| 2 | Technical indicators, chart pattern recognition | Done — indicators in `data_market_api.py`; support/resistance, candlestick patterns, breakouts, ATR in `signals_signal_engine.py` (computed from candle data, which beats OCR'ing chart pixels) |
| 3 | Recommendation engine | Done — `recommend_recommendation_engine.py`, now with trade plans (entry/stop/target/R:R) |
| 3.5 | Voice output | Done — `output_voice_alert.py`, wired into `main.py` |
| 3.6 | On-screen signal panel | Done — `output_screen_alert.py`, wired into `main.py` |
| 4 | Learning engine | Done — `learning_outcome_tracker.py` grades every announced call (stop or target hit?) and feeds win/loss back into `strategy_scores` |
| 5 | Streamlit dashboard | Not started (Flask portfolio dashboard exists in `athena_dashboard.py`) |
| 6 | Backtesting | Done — `backtest_engine.py`; feeds measured win rate + expectancy into every live signal |

## Files

```
main.py                          — entry point, run this
find_region.py                   — one-off helper to find --region coordinates

data_market_api.py               — yfinance wrapper: quotes, OHLCV, SMA/EMA/RSI
data_db.py                       — SQLite: candles, user_actions, trade_journal, strategy_scores

vision_screen_capture.py         — periodic screenshots via mss (read-only)
vision_ocr_reader.py             — EasyOCR + regex parser (prices/symbols/P&L)
vision_chart_detector.py         — finds WHERE the chart is on screen (split-screen aware: left/right/center)
vision_symbol_resolver.py        — reads WHAT is charted: crypto / NSE / BSE / US ticker / index -> yfinance symbol
vision_ui_detector.py            — OCR box -> UIElement mapping
vision_position_tracker.py       — Phase 2 placeholder

recommend_recommendation_engine.py — combines indicators + learning history into BUY/SELL/HOLD/WAIT + reasons
output_voice_alert.py            — speaks recommendations aloud (pyttsx3, offline TTS)
output_screen_alert.py           — always-on-top BUY/SELL panel on screen (tkinter, no install needed)

learning_outcome_tracker.py      — grades every BUY/SELL call to WIN/LOSS/EXPIRED, updates strategy_scores
learning_action_logger.py        — superseded by learning_outcome_tracker.py
learning_strategy_scorer.py      — superseded by learning_outcome_tracker.py
signals_signal_engine.py         — chart analysis: support/resistance, candlestick patterns, breakouts, ATR
backtest_engine.py               — replays the signal rules on history; win rate / expectancy per symbol

tests_test_*.py                  — 51 tests; run offline ones with: pytest -m "not network"
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
- Shows the signal on an always-on-top panel in the corner of your screen
  (green BUY / red SELL / orange HOLD / gray WAIT, with confidence and
  reasons; flashes on a fresh BUY or SELL) — unless `--no-overlay`.
  Drag the panel anywhere; double-click it to minimize/restore.

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

# AUTO mode: find the chart on screen by itself (split-screen friendly),
# focus OCR on just that area, recognize the symbol (crypto/Indian/US/index)
# and start tracking it — switches automatically when you change charts
python main.py --auto
```

How `--auto` works each cycle:
1. `vision_chart_detector.py` finds the chart by its candle colors (biggest
   green/red cluster on screen; falls back to blue line-chart detection) and
   reports which side it's on — so with a video or article on the other half
   of a split screen, only the chart side is read.
2. OCR runs on just the cropped chart area (faster + cleaner).
3. `vision_symbol_resolver.py` votes on the OCR text: `NSE:RELIANCE` →
   `RELIANCE.NS`, `BINANCE:BTCUSDT` → `BTC-USD`, `NASDAQ:AAPL` → `AAPL`,
   `NIFTY` → `^NSEI`. A bare word like `TSLA` needs two sightings; an
   explicit exchange prefix wins immediately.
4. A new symbol must be seen on two consecutive cycles before the tracker
   switches (OCR flickers; the tracker shouldn't).

Stop any time with `Ctrl+C` — it shuts down cleanly.

## Design notes / decisions

- **Order book**: yfinance has no free Level-2 depth. `get_orderbook()`
  returns `None` rather than fake data.
- **OCR parsing is regex-based for now.** It can't yet tell "this is the
  LTP" from "this is yesterday's high" — that needs `read_with_boxes()`
  (already implemented) paired with `ui_detector.py` mapped to your actual
  platform's layout. Still a Phase 2 task.
- **SELL is always announced on a bearish setup**, even without
  `--has-position` — in that case it means "exit if you hold this,
  don't buy now" (and the reason list says so).
- **Every BUY/SELL carries a trade plan**: entry, ATR/level-based
  stop-loss, target capped at the next resistance/support, risk and
  reward per share, and R:R ratio.
- **Estimates are measured, not promised.** Win rate and expected
  P&L/share come from backtesting the same rules on ~60 days of hourly
  candles for that symbol (cached 30 min). The stop-first tie-break in
  the backtester biases results *against* us on ambiguous bars.
- **Multi-timeframe confirmation**: every 15m signal is checked against
  the 1-hour trend (same cached download the backtester uses). A BUY
  against a 1-hour downtrend is vetoed; agreement adds confidence; a
  SELL during a 1-hour uptrend is softened to "may be a dip".
- **The engine refuses bad trades**: a BUY with risk:reward below 1:1,
  a BUY against the 1-hour trend, or one with measured negative
  expectancy (≥10 backtest trades), is downgraded to WAIT with the
  reason spelled out. No signal is ever
  "guaranteed" — the goal is positive expectancy over many trades, not
  being right every time (nothing is).
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

## How the learning loop works (Phase 4)

1. Every BUY/SELL announced with a trade plan is recorded as a paper call
   (`tracked_calls` table — survives restarts).
2. Each observe cycle, live prices are checked against the call's stop and
   target: target first → WIN, stop first → LOSS, 48h without either →
   EXPIRED (graded by whether it was up or down). Exits are booked AT the
   planned level. In `--auto` mode, calls left open on charts you switched
   away from are still graded on the slower rec-interval tick.
3. Every outcome updates `strategy_scores` for the call's `--setup-tag` —
   the same table the Recommendation Engine multiplies its score by. Setups
   that keep losing drag their own confidence down; setups that win earn
   more. The more calls it makes, the better calibrated it gets.

These are paper outcomes grading the advice — nothing is ever traded.

## Next step

Phase 5: a proper dashboard page for the learning engine — tracked calls,
per-setup win rates over time, expectancy curves. The Flask dashboard in
`athena_dashboard.py` already shows the trade journal these calls write to.
