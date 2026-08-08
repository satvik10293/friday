"""
core/brains/trading/brain.py — the Trading Brain (M63).

Wraps Athena (the vendored trading analyst in trading_ai/) as a first-class
Cognitive Brain, making her a SUBAGENT of FRIDAY: addressable by name ("ask the
trading brain about AAPL", "Athena, should I buy TCS", "portfolio"), part of the
society's health/roster, reporting her status on the Situation Report Bus.

Design contract (matches core/brains/base.py):
  * Side-effect-free to import — NOTHING from trading_ai is imported at module
    load or brain construction; the heavy engine (pandas + market data + DB) is
    built lazily only when the owner actually asks a trading question.
  * Never raises — a trading fault answers honestly, it never breaks the turn.
  * Degrades gracefully — the live broker (Angel One via SmartApi + credentials)
    is optional; without it Athena runs in advisory mode (chart/indicator reads),
    and the portfolio path says so plainly instead of crashing.

Advisory only: the subagent reads and analyses. It never places orders by voice.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

from ..base import CognitiveBrain, SituationReport

_TRADING_DIR = Path(__file__).resolve().parents[3] / "trading_ai"

# tokens that look like tickers but aren't
_NOT_TICKERS = {
    "I", "A", "AI", "AN", "THE", "OK", "BUY", "SELL", "AND", "OR", "MY", "IS",
    "ATHENA", "STOCK", "SHOULD", "TRADE", "IDEA", "USD", "INR", "PM", "AM",
}
_SYM_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,11}(?:\.[A-Z]{1,3})?)\b")
_AFTER_RE = re.compile(
    r"\b(?:buy|sell|about|for|on|analy[sz]e|idea|is|of)\s+"
    r"([A-Za-z][A-Za-z0-9.]{1,11})\b", re.I)
_PORTFOLIO_RE = re.compile(
    r"\b(portfolio|holding|my funds?|my account|balance|positions?)\b", re.I)
_REC_RE = re.compile(
    r"\b(buy|sell|should i|trade|idea|recommend|signal|analy[sz]e|target|"
    r"stop.?loss|what about|how'?s|how is)\b", re.I)


class TradingBrain(CognitiveBrain):
    name = "trading_brain"

    def __init__(self, *, services=None, config=None, report_bus=None) -> None:
        super().__init__(services=services, config=config, report_bus=report_bus)
        self._engine = None          # lazily built RecommendationEngine
        self._announced = False      # report availability once

    # ── lifecycle: report availability once, cheaply (no imports on ticks) ────────
    def observe(self):
        return {"present": _TRADING_DIR.is_dir(), "broker": self._broker_configured()}

    def generate_situation_report(self, insight) -> Optional[SituationReport]:
        if not insight.get("present") or self._announced:
            return None
        self._announced = True
        mode = "live broker" if insight.get("broker") else "advisory mode"
        return self._report(
            f"Athena trading subagent online ({mode}).",
            confidence=0.9, priority=0.2, category="trading",
            data={"broker": insight.get("broker", False)})

    # ── the subagent entry point: FRIDAY delegates trading questions here ─────────
    def ask(self, query: str) -> str:
        """Answer a trading question. Never raises; always returns a spoken line."""
        q = (query or "").strip()
        if not q:
            return ("Ask me about a stock — like 'Athena, should I buy AAPL?' — "
                    "or say 'portfolio' for your holdings.")
        try:
            if _PORTFOLIO_RE.search(q):
                return self._portfolio()
            symbol = self._symbol(q)
            if symbol and (_REC_RE.search(q) or "athena" in q.lower()):
                return self._recommend(symbol)
            if symbol:
                return self._recommend(symbol)
            return self._capabilities()
        except Exception:  # noqa: BLE001 — a trading fault never breaks the turn
            return "I couldn't analyse that just now."

    # ── recommendation (chart/indicator read; needs market data) ─────────────────
    def _recommend(self, symbol: str) -> str:
        engine = self._get_engine()
        if engine is None:
            return ("Athena's analysis engine isn't available right now — "
                    "her market libraries may be missing.")
        try:
            rec = engine.evaluate(symbol)
        except Exception:  # noqa: BLE001
            return f"I couldn't get data for {symbol} just now."
        line = f"{rec.action} on {rec.symbol} — {rec.confidence:.0f}% confidence."
        plan = getattr(rec, "plan", None)
        if plan is not None:
            line += (f" Entry {plan.entry:.2f}, stop {plan.stop_loss:.2f}, "
                     f"target {plan.target:.2f} (R:R 1:{plan.rr_ratio:.1f}).")
        reasons = getattr(rec, "reasons", None)
        if reasons:
            line += " " + reasons[0]
        return line

    # ── portfolio (live broker, optional) ────────────────────────────────────────
    def _portfolio(self) -> str:
        if not self._broker_configured():
            return ("Your Angel One account isn't connected — add your broker "
                    "credentials (API key + client code) and I'll pull live "
                    "holdings. For now I can still analyse any stock you name.")
        try:
            self._ensure_path()
            from angel_connector import AngelConnector  # type: ignore
            angel = AngelConnector()
            angel.login()
            return angel.create_summary()
        except Exception as e:  # noqa: BLE001
            return f"I couldn't reach your brokerage just now ({type(e).__name__})."

    def _capabilities(self) -> str:
        mode = "connected" if self._broker_configured() else "advisory mode"
        return (f"Athena, your trading analyst, is online — broker {mode}. "
                "Ask me for a read on any stock, like 'should I buy AAPL', or "
                "say 'portfolio' for your holdings.")

    # ── helpers ──────────────────────────────────────────────────────────────────
    def _symbol(self, q: str) -> Optional[str]:
        for tok in _SYM_RE.findall(q):
            if tok.upper() not in _NOT_TICKERS:
                return tok.upper()
        m = _AFTER_RE.search(q)
        if m and m.group(1).upper() not in _NOT_TICKERS:
            return m.group(1).upper()
        return None

    def _ensure_path(self) -> None:
        p = str(_TRADING_DIR)
        if _TRADING_DIR.is_dir() and p not in sys.path:
            sys.path.insert(0, p)

    def _get_engine(self):
        if self._engine is not None:
            return self._engine
        try:
            self._ensure_path()
            from recommend_recommendation_engine import RecommendationEngine  # type: ignore
            self._engine = RecommendationEngine()
        except Exception:  # noqa: BLE001 — missing market libs → advisory unavailable
            self._engine = None
        return self._engine

    @staticmethod
    def _broker_configured() -> bool:
        """Live broker needs the SmartApi SDK AND the Angel One credentials."""
        try:
            import importlib.util
            if importlib.util.find_spec("SmartApi") is None:
                return False
        except Exception:  # noqa: BLE001
            return False
        return all(os.getenv(k) for k in
                   ("API_KEY", "CLIENT_CODE", "PASSWORD", "TOTP_SECRET"))
