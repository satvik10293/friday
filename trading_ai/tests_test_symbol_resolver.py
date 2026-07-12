"""Offline tests for vision_symbol_resolver."""

from vision_symbol_resolver import resolve_symbol


def test_tradingview_nse_prefix():
    det = resolve_symbol(["NSE:RELIANCE", "1,307.80", "+2.14%"])
    assert det.symbol == "RELIANCE.NS"
    assert det.market == "india"


def test_tradingview_crypto_exchange_prefix():
    det = resolve_symbol(["BINANCE:BTCUSDT", "67,412.00"])
    assert det.symbol == "BTC-USD"
    assert det.market == "crypto"


def test_crypto_pair_with_slash():
    det = resolve_symbol(["BTC/USDT", "Perpetual"])
    assert det.symbol == "BTC-USD"
    assert det.market == "crypto"


def test_us_exchange_prefix():
    det = resolve_symbol(["NASDAQ:AAPL", "Apple Inc"])
    assert det.symbol == "AAPL"
    assert det.market == "us"


def test_bare_us_ticker_needs_two_sightings():
    assert resolve_symbol(["TSLA"]) is None          # one sighting: not enough
    det = resolve_symbol(["TSLA", "TSLA 244.40"])    # twice: convincing
    assert det.symbol == "TSLA"
    assert det.market == "us"


def test_known_indian_stock_bare_name():
    det = resolve_symbol(["TATAMOTORS", "775.20"])
    assert det.symbol == "TATAMOTORS.NS"
    assert det.market == "india"


def test_index_name():
    det = resolve_symbol(["NIFTY", "24,141.30"])
    assert det.symbol == "^NSEI"
    assert det.market == "index"


def test_ocr_semicolon_instead_of_colon():
    det = resolve_symbol(["NSE;TCS"])
    assert det.symbol == "TCS.NS"


def test_explicit_yfinance_suffix():
    det = resolve_symbol(["WIPRO.NS"])
    assert det.symbol == "WIPRO.NS"
    assert det.market == "india"


def test_junk_text_resolves_to_nothing():
    assert resolve_symbol(["THE", "OPEN", "HIGH", "LOW", "12.5", "%"]) is None


def test_console_words_are_not_tickers():
    # Regression: live testing once resolved 'NONE' off a console window
    assert resolve_symbol(["memory-None) :", "ERROR", "NONE", "NONE"]) is None


def test_exchange_prefix_beats_stray_words():
    det = resolve_symbol(["NSE:SBIN", "LIVE", "GOLD", "NOW"])
    assert det.symbol == "SBIN.NS"
