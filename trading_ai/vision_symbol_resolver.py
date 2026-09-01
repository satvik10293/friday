"""
Eye 2, Stage 4 — Symbol Resolver.

Takes raw OCR text read off the chart area and figures out WHAT is being
charted — crypto, Indian stock (NSE/BSE), US stock, or an index — and
converts it to the yfinance symbol the data layer understands:

    "NSE:RELIANCE"      -> RELIANCE.NS   (india)
    "BINANCE:BTCUSDT"   -> BTC-USD       (crypto)
    "BTC/USDT"          -> BTC-USD       (crypto)
    "NASDAQ:AAPL"       -> AAPL          (us)
    "AAPL"              -> AAPL          (us, needs 2+ sightings)
    "NIFTY"             -> ^NSEI         (index)

Evidence-based, not first-match: every candidate earns points per sighting
(exchange-prefixed text is worth the most, a bare 4-letter word the least)
and the highest-scoring candidate wins — but only if it clears a minimum
score, so a random word OCR'd off a webpage doesn't hijack the tracker.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# TradingView-style EXCHANGE:SYMBOL prefixes (OCR sometimes reads ':' as ';')
_EXCHANGE_MAP: Dict[str, Tuple[str, str]] = {
    # exchange -> (suffix to append, market)
    "NSE": (".NS", "india"),
    "BSE": (".BO", "india"),
    "NASDAQ": ("", "us"),
    "NYSE": ("", "us"),
    "AMEX": ("", "us"),
    "CBOE": ("", "us"),
}
_CRYPTO_EXCHANGES = {
    "BINANCE", "COINBASE", "BYBIT", "KRAKEN", "KUCOIN",
    "OKX", "MEXC", "BITSTAMP", "BITGET", "GEMINI",
}
_CRYPTO_QUOTES = ("USDT", "USDC", "BUSD", "USD", "INR", "EUR")
_CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "DOT", "MATIC", "POL",
    "SHIB", "LTC", "AVAX", "LINK", "TRX", "PEPE", "UNI", "ATOM", "XLM",
    "NEAR", "APT", "ARB", "OP", "FIL", "INJ", "SUI", "TON", "HBAR", "ALGO",
}
# Common NSE tickers so a bare "RELIANCE" resolves to the Indian feed
_NSE_STOCKS = {
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK",
    "KOTAKBANK", "ITC", "WIPRO", "HCLTECH", "TECHM", "LT", "TATAMOTORS",
    "TATASTEEL", "TATAPOWER", "ADANIENT", "ADANIPORTS", "ADANIGREEN",
    "BAJFINANCE", "BAJAJFINSV", "MARUTI", "SUNPHARMA", "CIPLA", "DRREDDY",
    "HINDUNILVR", "NESTLEIND", "TITAN", "ASIANPAINT", "ULTRACEMCO",
    "JSWSTEEL", "COALINDIA", "ONGC", "NTPC", "POWERGRID", "BHARTIARTL",
    "IRCTC", "ZOMATO", "PAYTM", "DMART", "HAL", "BEL", "IDEA", "YESBANK",
}
_INDEX_MAP = {
    "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN", "SPX": "^GSPC", "SP500": "^GSPC",
    "NDX": "^NDX", "DJI": "^DJI", "DOWJONES": "^DJI",
}
# Words OCR picks up constantly that are NOT tickers
_IGNORE = {
    "THE", "AND", "FOR", "ALL", "NEW", "OPEN", "HIGH", "LOW", "CLOSE", "VOL",
    "BUY", "SELL", "WAIT", "HOLD", "CHART", "TRADE", "PRICE", "TOTAL", "DAY",
    "WEEK", "MONTH", "YEAR", "LIVE", "NOW", "GET", "SET", "TOP", "ADD",
    "OCR", "CPU", "GPU", "USD", "INR", "EUR", "USDT", "USDC", "LTP", "AVG",
    "MKT", "QTY", "MIS", "CNC", "NRML", "YOU", "ARE", "CAN", "NOT", "PRO",
    "APP", "TAB", "MAX", "MIN", "AGO", "PER", "OFF", "OUT", "ONE", "TWO",
    # console/UI words that showed up as false positives in live testing
    "NONE", "NULL", "TRUE", "FALSE", "ERROR", "INFO", "WARN", "CODE", "FILE",
    "EDIT", "READ", "LINE", "TEST", "MAIN", "DATA", "TIME", "DATE", "USER",
    "HOME", "SAVE", "HELP", "MODE", "AUTO", "SCAN", "LOAD", "NAME", "TYPE",
    # exchange names must not vote as bare tickers themselves
    "NSE", "BSE", "NYSE", "AMEX", "CBOE", "OKX", "MEXC",
}

# Common English words OCR grabs from prose/chat/terminal — none should ever be
# read as a ticker in auto mode. (Some ARE real tickers, e.g. ALL/SHE/IT — a user
# who truly wants one runs --no-auto --symbol ALL. Auto mode must not lock onto a
# word from text; that's the 'She' -> SHE bug this kills.)
_IGNORE |= {
    "SHE", "HER", "HIM", "HIS", "HERS", "THEY", "THEM", "YOUR", "YOURS", "MINE",
    "OURS", "WHO", "WHOM", "WHOSE", "THIS", "THAT", "THESE", "THOSE", "WHEN",
    "WHERE", "WHY", "HOW", "WHICH", "WHAT", "WAS", "WERE", "HAVE", "HAD", "WILL",
    "WONT", "WOULD", "CANT", "COULD", "SHALL", "SHOULD", "MAY", "MIGHT", "MUST",
    "DID", "DONT", "DOES", "DONE", "MAKE", "MADE", "TAKE", "TOOK", "GAVE", "GIVE",
    "GOES", "WENT", "COME", "CAME", "SAW", "SAYS", "SAID", "NEED", "KNOW", "KNEW",
    "LOOK", "FIND", "TELL", "FIX", "KEEP", "WITH", "FROM", "INTO", "ONTO", "OVER",
    "THAN", "THEN", "ABLE", "ALSO", "JUST", "VERY", "MUCH", "MANY", "MORE", "MOST",
    "SOME", "EACH", "BOTH", "EVEN", "STILL", "LIKE", "GOOD", "BEST", "REAL", "SURE",
    "SAME", "NEXT", "LAST", "HARD", "EASY", "LONG", "FULL", "HALF", "LATE", "SOON",
    "HERE", "WELL", "OKAY", "YES", "YEAH", "HEY", "LOL", "PLS", "THX", "BUT", "NOR",
    "YET", "WHATS", "THATS", "ITS", "IVE", "LETS", "GOING", "DOING", "BEING", "WORD",
    "WORDS", "THING", "THINGS", "STUFF", "KIND", "EVERY", "ONCE", "ELSE", "WORK",
    "RSI", "MACD", "EMA", "SMA", "ATR", "ADX", "UTF", "CRLF", "JSON", "HTTP",
}

_EXCHANGE_RE = re.compile(r"\b([A-Z]{3,10})\s*[:;]\s*([A-Z0-9]{1,15})\b")
_PAIR_RE = re.compile(r"\b([A-Z]{2,6})\s*[/\-]?\s*(USDT|USDC|BUSD|USD|INR|EUR)\b")
_SUFFIXED_RE = re.compile(r"\b([A-Z]{2,12})\.(NS|BO)\b")
_BARE_RE = re.compile(r"\b[A-Z]{2,10}\b")


@dataclass
class DetectedSymbol:
    symbol: str       # yfinance-ready, e.g. "BTC-USD", "RELIANCE.NS", "AAPL"
    market: str       # "crypto" | "india" | "us" | "index"
    score: float      # accumulated evidence
    source_text: str  # the OCR fragment that triggered it (for debugging)


def _crypto_symbol(pair_text: str) -> Optional[Tuple[str, str]]:
    """'BTCUSDT' / 'BTC/USD' / 'ETH-USDC' -> ('BTC-USD', base)."""
    cleaned = pair_text.replace("/", "").replace("-", "").replace(" ", "")
    for quote in _CRYPTO_QUOTES:
        if cleaned.endswith(quote) and len(cleaned) > len(quote):
            base = cleaned[: -len(quote)]
            if 2 <= len(base) <= 6:
                yf_quote = "INR" if quote == "INR" else ("EUR" if quote == "EUR" else "USD")
                return f"{base}-{yf_quote}", base
    return None


def resolve_symbol(texts: List[str], min_score: float = 2.0) -> Optional[DetectedSymbol]:
    """
    Votes across all OCR fragments and returns the best symbol candidate,
    or None if nothing is convincing enough.

    Scoring per sighting:
      3.0  EXCHANGE:SYMBOL prefix or explicit .NS/.BO suffix  (unambiguous)
      2.0  crypto pair (BTC/USDT), known NSE name, known index name
      1.5  bare known crypto base ("BTC" alone -> BTC-USD)
      1.0  bare 3-5 letter word (could be a US ticker — needs 2+ sightings).
           2-letter bare words are rejected: from prose they're almost always
           noise ("is", "as", "on"); real 2-letter tickers (GM, GE) arrive with
           an exchange prefix and score via that path instead.
    """
    scores: Dict[Tuple[str, str], float] = defaultdict(float)
    sources: Dict[Tuple[str, str], str] = {}
    strong: set = set()          # keys seen via a structured source (>=1.5/vote)

    def vote(symbol: str, market: str, points: float, source: str) -> None:
        key = (symbol, market)
        scores[key] += points
        sources.setdefault(key, source)
        if points >= 1.5:        # exchange-prefix / .NS / crypto pair / known name
            strong.add(key)

    for raw in texts:
        text = raw.upper().strip()
        if not text:
            continue

        for exchange, sym in _EXCHANGE_RE.findall(text):
            if exchange in _EXCHANGE_MAP:
                suffix, market = _EXCHANGE_MAP[exchange]
                vote(sym + suffix, market, 3.0, raw)
            elif exchange in _CRYPTO_EXCHANGES:
                crypto = _crypto_symbol(sym)
                if crypto:
                    vote(crypto[0], "crypto", 3.0, raw)

        for sym, suffix in _SUFFIXED_RE.findall(text):
            vote(f"{sym}.{suffix}", "india", 3.0, raw)

        for base, quote in _PAIR_RE.findall(text):
            if base in _CRYPTO_BASES:
                crypto = _crypto_symbol(base + quote)
                if crypto:
                    vote(crypto[0], "crypto", 2.0, raw)

        for word in _BARE_RE.findall(text):
            if word in _IGNORE:
                continue
            if word in _INDEX_MAP:
                vote(_INDEX_MAP[word], "index", 2.0, raw)
            elif word in _NSE_STOCKS:
                vote(f"{word}.NS", "india", 2.0, raw)
            elif word in _CRYPTO_BASES:
                vote(f"{word}-USD", "crypto", 1.5, raw)
            elif 3 <= len(word) <= 5:
                vote(word, "us", 1.0, raw)

    if not scores:
        return None

    # A real chart labels its ticker structurally (NASDAQ:AAPL, RELIANCE.NS,
    # BTC/USDT). If ANY such strong candidate is present, ignore bare words
    # scraped from surrounding prose — this is what stops "She" -> SHE, "break"
    # -> BREAK, and other text hijacking the tracker.
    if strong:
        scores = {k: v for k, v in scores.items() if k in strong}

    (symbol, market), best = max(scores.items(), key=lambda kv: kv[1])
    if best < min_score:
        return None
    return DetectedSymbol(symbol=symbol, market=market, score=best,
                          source_text=sources[(symbol, market)])
