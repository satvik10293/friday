"""
core/services/attention_service.py — FRIDAY V3 (M16)
AttentionService — salience ranking behind a stable API. Adapts the M5 `AttentionSystem`
(`rank_observations`) and falls back to an importance/confidence sort when none is wired.
"""

from __future__ import annotations

import logging

log = logging.getLogger("friday.services.attention")


class AttentionService:
    name = "attention"

    def __init__(self, attention_system=None) -> None:
        self._attn = attention_system

    def rank(self, items: list) -> list:
        """Rank a list of signal dicts (with importance/priority/urgency) by salience."""
        if self._attn is not None and hasattr(self._attn, "rank_observations"):
            try:
                scored = self._attn.rank_observations(list(items))
                return [s.to_dict() if hasattr(s, "to_dict") else s for s in scored]
            except Exception:  # noqa: BLE001
                log.debug("attention rank failed", exc_info=True)
        return sorted(items, key=lambda x: float(x.get("importance", x.get("priority", 0.0))),
                      reverse=True)

    def health(self) -> dict:
        return {"status": "ok", "backend": "attention_system" if self._attn else "fallback_sort"}
