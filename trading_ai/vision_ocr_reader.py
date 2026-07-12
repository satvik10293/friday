"""
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
IGNORE_SYMBOLS = {
    "OCR",
    "CPU",
    "GPU",
    "VOICE",
    "SIGNAL",
    "ENG",
    "PM",
    "PS",
    "PY",
    "YOU",
    "THE",
    "BUY",
    "SELL",
    "WAIT",
    "ALERT"
}

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
        """
        Returns OCR text after filtering low-confidence detections.
        """

        results = self.reader.readtext(
            image,
            detail=1
        )

        filtered = []

        for box, text, confidence in results:

            if confidence < 0.50:
                continue

            text = text.strip()

            if not text:
                continue

            filtered.append(text)

        return filtered
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

            for symbol in sym_matches:

                symbol = symbol.upper()

                if symbol in IGNORE_SYMBOLS:
                    continue

                if len(symbol) > 5:
                    continue

                symbols.append(symbol)
            if any(c.isdigit() for c in cleaned):
                price_matches = _PRICE_RE.findall(cleaned)
                for p in price_matches:
                    p_clean = p.replace(",", "")
                    try:
                        if p_clean and p_clean not in (".", "-", "+"):
                            value = float(p_clean)

                            if value <= 0:
                                continue

                            if value > 100000:
                                continue

                            prices.append(value)
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
