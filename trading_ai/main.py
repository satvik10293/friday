"""
main.py — Screen-Aware Trading Assistant entry point.

Wires together everything built so far into one running loop:

  Eye 1 (data_market_api)      -> live quote every cycle
  Eye 2 (vision_screen_capture
         + vision_ocr_reader)  -> screen capture + OCR every cycle (optional)
  Recommendation Engine        -> BUY/SELL/HOLD/WAIT every N seconds
  Voice Alert                  -> speaks the recommendation aloud (optional)
  Screen Alert                 -> always-on-top BUY/SELL panel on screen (optional)
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
    parser.add_argument("--auto", action="store_true",
                        help="Auto-detect the chart on screen (even in a split screen), focus OCR on "
                             "just that area, recognize the symbol (crypto/Indian/US), and track it")
    parser.add_argument("--interval", type=float, default=3.0, help="Seconds between observe cycles (1-5s recommended)")
    parser.add_argument("--region", type=str, default=None, help="Screen region to capture: LEFT,TOP,WIDTH,HEIGHT (default: full primary monitor)")
    parser.add_argument("--monitor-index", type=int, default=1, help="Which monitor to capture when --region is not set (mss numbering, 1=primary)")
    parser.add_argument("--no-screen", action="store_true", help="Skip screen capture + OCR entirely (market data only)")
    parser.add_argument("--no-voice", action="store_true", help="Disable spoken voice alerts (console/log only)")
    parser.add_argument("--no-overlay", action="store_true", help="Disable the on-screen BUY/SELL signal panel")
    parser.add_argument("--gpu", action="store_true", help="Use GPU for OCR if available (default: CPU)")
    parser.add_argument("--rec-interval", type=float, default=60.0, help="Seconds between recommendation evaluations (default 60s, keeps yfinance calls reasonable)")
    parser.add_argument("--has-position", action="store_true", help="Tell the engine you currently have an open position (changes BUY/SELL -> HOLD/SELL semantics)")
    parser.add_argument("--setup-tag", default="trend_continuation", help="Strategy/setup label used for learning-engine lookups and trade journal tagging")
    return parser


def main() -> int:
    # Windows consoles often default to cp1252, which can't print characters
    # like Δ and would crash the loop. Force UTF-8 with a safe fallback.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_arg_parser().parse_args()
    region = parse_region(args.region)

    if args.auto and args.no_screen:
        print("--auto needs screen capture; remove --no-screen")
        return 2

    market = MarketDataClient()
    db = Database()
    engine = RecommendationEngine(market=market, db=db)

    from learning_outcome_tracker import OutcomeTracker
    tracker = OutcomeTracker(db=db)
    t_stats = tracker.stats()
    if t_stats["open"] or t_stats["closed"]:
        win_txt = (f"{t_stats['win_rate'] * 100:.0f}% wins"
                   if t_stats["win_rate"] is not None else "no closed calls yet")
        print(f"[Learning] resuming: {t_stats['open']} open tracked calls, "
              f"{t_stats['closed']} graded so far ({win_txt})")

    screen_capture = None
    ocr_reader = None
    find_chart_region = resolve_symbol = None
    if not args.no_screen:
        from vision_screen_capture import ScreenCapture
        from vision_ocr_reader import OCRReader

        screen_capture = ScreenCapture(monitor_index=args.monitor_index, region=region)
        ocr_reader = OCRReader(gpu=args.gpu)

        if args.auto:
            from vision_chart_detector import find_chart_region
            from vision_symbol_resolver import resolve_symbol

    voice = None
    if not args.no_voice:
        try:
            from output_voice_alert import VoiceAlert

            voice = VoiceAlert()
        except ImportError as exc:
            print(f"[WARN] Voice alerts disabled — {exc}")

    overlay = None
    if not args.no_overlay:
        try:
            from output_screen_alert import ScreenAlert

            overlay = ScreenAlert()
        except Exception as exc:  # tkinter/display issues shouldn't kill the loop
            print(f"[WARN] On-screen panel disabled — {exc}")

    current_symbol = args.symbol
    pending_symbol = None  # a newly seen symbol must show up twice in a row before we switch
    rejected_symbols = {}  # symbol -> time it failed validation; don't retry for a while
    REJECT_COOLDOWN = 600.0

    if args.auto:
        print(f"AUTO mode: scanning your screen for a chart | starting on {current_symbol} "
              f"until one is recognized | Ctrl+C to stop")
    else:
        print(f"Watching {current_symbol} | cycle every {args.interval}s | "
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
                quote = market.get_quote(current_symbol)
                arrow = "Δ" if quote.change_pct is None else f"Δ {quote.change_pct:+.3f}%"
                print(f"[Market]  {quote.symbol}: {quote.price:.2f}  ({arrow})  vol={quote.volume}")
                if overlay is not None:
                    overlay.update_price(quote.symbol, quote.price, quote.change_pct)

                # ---- Learning engine: grade any open call on this symbol ----
                for outcome in tracker.check(current_symbol, quote.price):
                    print(f"[Learning] {outcome}")
                    db.log_action(symbol=outcome.symbol, action="CLOSE",
                                  price=outcome.exit_price,
                                  reason=f"{outcome.status} {outcome.direction} call "
                                         f"({outcome.pnl_per_share:+.2f}/share)",
                                  source="learning")
            except MarketAPIError as exc:
                print(f"[Market]  error: {exc}")

            # ---- Eye 2: screen vision (optional) ----
            if screen_capture is not None and ocr_reader is not None:
                try:
                    frame = screen_capture.capture_once()
                    image = frame.image
                    chart_note = ""

                    # In auto mode, find the chart first and OCR only that
                    # area — a split screen with a video/article on the other
                    # side no longer pollutes the reading.
                    if args.auto:
                        chart = find_chart_region(image)
                        if chart is not None:
                            image = chart.crop(image)
                            chart_note = f"  [chart: {chart.side} side, {chart.chart_type}]"
                        else:
                            chart_note = "  [no chart visible]"

                    result = ocr_reader.read_and_parse(image)
                    print(f"[Screen]  symbols={result.symbols}  prices={result.prices}  "
                          f"pnl={result.pnl_candidates}{chart_note}")

                    if args.auto:
                        detected = resolve_symbol(result.raw_text)
                        if detected is not None:
                            sym = detected.symbol
                            recently_rejected = (
                                time.time() - rejected_symbols.get(sym, -1e12) < REJECT_COOLDOWN
                            )
                            if sym != current_symbol and not recently_rejected:
                                if sym == pending_symbol:
                                    # OCR words can lie ("NONE" off a console once
                                    # passed for a ticker in testing) — only switch
                                    # if the data feed confirms it's real.
                                    try:
                                        market.get_quote(sym)
                                        current_symbol = sym
                                        last_rec_time = 0.0  # analyze the new chart immediately
                                        print(f"[Screen]  >>> Chart recognized: now tracking "
                                              f"{current_symbol} ({detected.market}, "
                                              f"from '{detected.source_text}')")
                                    except MarketAPIError:
                                        rejected_symbols[sym] = time.time()
                                        print(f"[Screen]  ignoring '{sym}' — no such symbol in the data feed")
                                pending_symbol = sym
                except Exception as exc:  # vision is best-effort; never crash the loop over it
                    print(f"[Screen]  error: {exc}")

            # ---- Recommendation engine, throttled to --rec-interval ----
            now = time.time()
            if quote is not None and (now - last_rec_time) >= args.rec_interval:
                last_rec_time = now

                # Grade open calls on OTHER symbols too (auto mode may have
                # switched charts and left calls behind) — on the slow tick
                # only, since each one is a network quote.
                for outcome in tracker.check_all(market.get_quote, exclude=current_symbol):
                    print(f"[Learning] {outcome}")

                rec = engine.evaluate(
                    current_symbol,
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

                # Track this call so its outcome teaches future scoring
                if rec.action in ("BUY", "SELL") and rec.plan is not None:
                    call_id = tracker.track(current_symbol, rec.action, rec.plan,
                                            args.setup_tag, price=quote.price)
                    if call_id is not None:
                        print(f"[Learning] now tracking this {rec.action} call "
                              f"(stop {rec.plan.stop_loss:.2f} / target {rec.plan.target:.2f}) "
                              f"— outcome will update '{args.setup_tag}' scores")

                if voice is not None:
                    voice.announce(rec)

                if overlay is not None:
                    overlay.show(rec, price=quote.price)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        if voice is not None:
            voice.stop()
        if overlay is not None:
            overlay.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
