"""
core/review/ — FRIDAY 4.0 (M10)
The Design Challenge Gate: a milestone must answer hard questions about its own
design *before* any implementation begins. Operationalises the mandate from
docs/ARCHITECTURE_REVIEW.md §9 — challenge the design before coding.

Side-effect-free to import.
"""

from __future__ import annotations

from .design_gate import (DesignGate, DesignGateResult, DesignQuestion,
                          DesignReview, QUESTIONS, get_design_gate)

__all__ = ["DesignGate", "DesignGateResult", "DesignQuestion", "DesignReview",
           "QUESTIONS", "get_design_gate"]
