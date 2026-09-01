"""
A2 — screen-reading robustness. The symbol resolver must read the RIGHT ticker
off a chart and never lock onto a word scraped from prose/terminal (the live
'She' -> SHE / 'break' -> BREAK bug).
"""

from __future__ import annotations

from vision_symbol_resolver import resolve_symbol


def _sym(texts):
    r = resolve_symbol(texts)
    return r.symbol if r else None


def test_a_charts_labelled_symbol_wins_over_prose():
    # a real chart labels NASDAQ:AAPL; my chat prose is also on screen
    screen = ["NASDAQ:AAPL", "AAPL", "AAPL 316.85",
              "me break this into what is real", "She is live now", "this was that"]
    assert _sym(screen * 2) == "AAPL"


def test_indian_and_crypto_charts_resolve_through_prose():
    assert _sym(["NSE:RELIANCE", "RELIANCE.NS", "she said break this"]) == "RELIANCE.NS"
    assert _sym(["BINANCE:BTCUSDT", "BTC/USDT", "break was here now"]) == "BTC-USD"


def test_common_words_never_resolve_as_tickers():
    # the exact prose that made her lock onto SHE in the live session — no chart
    prose = ["She is live now", "what is real", "this that was", "RSI", "AUTO", "US", "NS"]
    r = resolve_symbol(prose * 3)
    assert r is None or r.symbol not in {"SHE", "IS", "WAS", "THIS", "THAT", "RSI", "US", "NS"}


def test_two_letter_bare_words_are_rejected():
    # 2-letter prose words ("is", "as", "on") must not become tickers
    assert _sym(["is", "as", "on", "of", "to"] * 3) is None


def test_a_clean_bare_ticker_still_works_without_structure():
    # when there's no exchange prefix at all, a clean repeated 3-5 letter ticker
    # can still resolve (needs 2+ sightings)
    assert _sym(["TSLA", "TSLA"]) == "TSLA"
