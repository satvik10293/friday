"""
core/reasoning/substrate.py — FRIDAY 5.x (M54)
The language substrate the deliberate mind thinks *with*.

The reasoning is FRIDAY's own (see engine.py); the substrate is only the
faculty that turns a prompt into words and back. Keeping it behind a tiny
protocol means the SAME brain runs over whatever's available:

    · LocalSubstrate    — the pulled on-device model (LocalReasoner), sharpest
    · ModelTeamSubstrate — the always-present builtin model team, so she
                           reasons TODAY with zero download
    · a stub in tests    — so the reasoning architecture is verifiable without
                           any model at all

None of these raise: a substrate that can't answer returns "" and the engine
copes (falls back, lowers confidence, or defers to the rest of the chain).
"""

from __future__ import annotations

import logging
from typing import Optional, Protocol

log = logging.getLogger("friday.reasoning.substrate")


class Substrate(Protocol):
    """The minimal language faculty the deliberate mind needs."""

    # how much the engine should trust prose from this faculty (0–1). Exact
    # steps (arithmetic) always override this; it only calibrates generative
    # steps, so a weak substrate's answers escalate instead of being trusted.
    base_confidence: float

    def available(self) -> bool: ...

    def generate(self, prompt: str, *, context: Optional[dict] = None,
                 temperature: float = 0.3) -> str: ...


class LocalSubstrate:
    """The pulled on-device model (LocalReasoner). Its own draft→critique pass
    is a fine per-utterance faculty; the deliberate engine wraps it with
    decomposition, tool grounding, and verification on top."""

    base_confidence = 0.78          # a real reasoning model — trusted to stand alone

    def __init__(self, local_reasoner) -> None:
        self._lr = local_reasoner

    def available(self) -> bool:
        try:
            return bool(self._lr) and self._lr.available()
        except Exception:  # noqa: BLE001
            return False

    def generate(self, prompt: str, *, context: Optional[dict] = None,
                 temperature: float = 0.3) -> str:
        try:
            ans = self._lr.reason(prompt, context=context)
            return ans.answer if getattr(ans, "ok", False) else ""
        except Exception:  # noqa: BLE001 — a faculty fault is never fatal
            log.debug("local substrate generate failed", exc_info=True)
            return ""


class ModelTeamSubstrate:
    """The always-available builtin model team via the Intelligence OS. Weaker
    than a real LLM, but it lets the deliberate architecture run from day one —
    and every exact step (math/code) is computed, not guessed, so even a weak
    substrate yields correct arithmetic and grounded structure."""

    base_confidence = 0.5           # weak: its prose should DEFER (escalate)

    def __init__(self, ios) -> None:
        self._ios = ios

    def available(self) -> bool:
        return self._ios is not None

    def generate(self, prompt: str, *, context: Optional[dict] = None,
                 temperature: float = 0.3) -> str:
        try:
            resp = self._ios.think(prompt, context=dict(context or {}))
            return getattr(resp, "answer", "") or "" if getattr(resp, "ok", False) else ""
        except Exception:  # noqa: BLE001
            log.debug("model-team substrate generate failed", exc_info=True)
            return ""


def best_substrate(*, local_reasoner=None, ios=None) -> Optional[Substrate]:
    """Pick the sharpest available substrate: the pulled local model if ready,
    else the builtin team, else None (no faculty at all)."""
    if local_reasoner is not None:
        sub = LocalSubstrate(local_reasoner)
        if sub.available():
            return sub
    if ios is not None:
        return ModelTeamSubstrate(ios)
    return None
