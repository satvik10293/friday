"""
core/perception/hub/confidence.py — FRIDAY V3 (M17)
The confidence engine. Combines per-sensor confidences into one unified confidence using
noisy-OR (independent corroborating evidence raises certainty), with an explicit boost
when multiple independent sensors agree and a penalty when they conflict. Conflicts are
handled gracefully — the engine never returns a value outside [0, 1] and reports the
conflict so the caller can decide.
"""

from __future__ import annotations

from typing import Optional

from .config import ConfidenceConfig


class ConfidenceEngine:
    def __init__(self, config: Optional[ConfidenceConfig] = None) -> None:
        self.config = config or ConfidenceConfig()

    def combine(self, confidences: list, *, agreement: bool = False,
                conflict: bool = False) -> float:
        """Fuse a list of confidences (each in [0, 1]) into one. `agreement` boosts when
        independent sensors corroborate; `conflict` penalizes contradictions."""
        vals = [max(0.0, min(1.0, float(c))) for c in confidences if c is not None]
        if not vals:
            return 0.0
        # noisy-OR: 1 - Π(1 - c)
        prod = 1.0
        for c in vals:
            prod *= (1.0 - c)
        fused = 1.0 - prod
        if agreement and len(vals) >= self.config.min_sources_for_boost:
            fused = min(1.0, fused + self.config.agreement_boost)
        if conflict:
            fused = max(0.0, fused - self.config.conflict_penalty)
        return round(fused, 4)

    def unify(self, modality_observations: list) -> dict:
        """Combine a group of modality observations. Detects conflict (same category at a
        location reported with very different confidence isn't a conflict; differing
        *labels* for the same exclusive category is). Returns
        {confidence, agreement, conflict, sources}."""
        if not modality_observations:
            return {"confidence": 0.0, "agreement": False, "conflict": False, "sources": 0}
        sources = {o.source for o in modality_observations}
        agreement = len(sources) >= self.config.min_sources_for_boost
        conflict = self._detect_conflict(modality_observations)
        confidence = self.combine([o.confidence for o in modality_observations],
                                  agreement=agreement and not conflict, conflict=conflict)
        return {"confidence": confidence, "agreement": agreement, "conflict": conflict,
                "sources": len(sources)}

    @staticmethod
    def _detect_conflict(observations: list) -> bool:
        """A conflict is two sensors asserting mutually-exclusive states for the same
        thing — e.g. spatial says the user is 'present' while another says 'unavailable'."""
        states = {o.data.get("user_state") for o in observations
                  if o.category == "user_state" and o.data.get("user_state")}
        if "unavailable" in states and (states - {"unavailable"}):
            return True
        return False
