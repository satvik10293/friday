"""
core/user_model/communication_model.py — FRIDAY 4.0 (M9)
Learns *how the user likes to be talked to* and lets FRIDAY adapt. Four aspects,
each a learned 0..1 dial:

    detail_level     0 brief        → 1 detailed
    technical_depth  0 simple       → 1 technical
    structure        0 prose        → 1 structured (bullets/steps)
    terminology      0 layman       → 1 domain jargon

Signals come from observed conversation cues (the user asks for "more detail",
"just the steps", "explain simply", …). Each cue nudges the relevant dial.
"""

from __future__ import annotations

from typing import Optional

from .models import CommunicationAspect, now
from .store import UserModelEvent, UserModelStore

_DEFAULT = 0.5


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


class CommunicationModel:
    def __init__(self, store: UserModelStore, emit=None, *, rate: float = 0.15) -> None:
        self._store = store
        self._emit = emit
        self._rate = rate

    def observe(self, aspect: str, *, higher: bool = True,
                strength: float = 1.0) -> float:
        """Nudge an aspect up (higher=True) or down. Returns the new value."""
        row = self._store.get_communication(aspect)
        value = row["value"] if row else _DEFAULT
        evidence = (row["evidence_count"] if row else 0) + 1
        value = _clamp(value + self._rate * strength * (1.0 if higher else -1.0))
        self._store.save_communication(aspect, value, evidence)
        self._store.record_metric("user.communication.adapted")
        if self._emit:
            self._emit(UserModelEvent.LEARNING_ADAPTED,
                       {"aspect": aspect, "value": value})
        return value

    # convenience signals ---------------------------------------------------------
    def wants_more_detail(self):  return self.observe(CommunicationAspect.DETAIL_LEVEL.value, higher=True)
    def wants_less_detail(self):  return self.observe(CommunicationAspect.DETAIL_LEVEL.value, higher=False)
    def wants_more_technical(self): return self.observe(CommunicationAspect.TECHNICAL_DEPTH.value, higher=True)
    def wants_simpler(self):      return self.observe(CommunicationAspect.TECHNICAL_DEPTH.value, higher=False)
    def wants_structure(self):    return self.observe(CommunicationAspect.STRUCTURE.value, higher=True)
    def wants_prose(self):        return self.observe(CommunicationAspect.STRUCTURE.value, higher=False)

    def value(self, aspect: str) -> float:
        row = self._store.get_communication(aspect)
        return row["value"] if row else _DEFAULT

    def style(self) -> dict:
        """The current communication style across all aspects, with labels."""
        out = {}
        for aspect in CommunicationAspect:
            v = self.value(aspect.value)
            out[aspect.value] = {"value": round(v, 3), "label": self._label(aspect.value, v)}
        return out

    @staticmethod
    def _label(aspect: str, v: float) -> str:
        lo_hi = {
            CommunicationAspect.DETAIL_LEVEL.value: ("brief", "detailed"),
            CommunicationAspect.TECHNICAL_DEPTH.value: ("simple", "technical"),
            CommunicationAspect.STRUCTURE.value: ("prose", "structured"),
            CommunicationAspect.TERMINOLOGY.value: ("layman", "domain"),
        }.get(aspect, ("low", "high"))
        if v >= 0.66:
            return lo_hi[1]
        if v <= 0.34:
            return lo_hi[0]
        return "balanced"

    def adapt_hint(self) -> dict:
        """A compact instruction set a responder/LLM can apply directly."""
        s = self.style()
        return {aspect: meta["label"] for aspect, meta in s.items()}
