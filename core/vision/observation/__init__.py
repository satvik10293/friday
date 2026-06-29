"""
core/vision/observation/ — FRIDAY 6.1 (M14) Observation Builder.

The single boundary that converts raw vision-processing results into the standardized
`core.perception.Observation` objects the rest of FRIDAY consumes. Vision produces
observations here and nowhere else; processors never build observations and never touch
the World Model.
"""

from __future__ import annotations

from .builder import ObservationBuilder

__all__ = ["ObservationBuilder"]
