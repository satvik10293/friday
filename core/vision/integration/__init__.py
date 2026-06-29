"""
core/vision/integration/ — FRIDAY 6.1 (M14) Cognitive Integration.

The bridge from visual perception into cognition: Observations are routed through the
existing Attention → Perception → Entity Resolver → World Model path (never bypassing
it), scene objects are linked to permanent stable ids, and visual events are recorded
and published. Vision is a perception subsystem only — reasoning lives downstream.
"""

from __future__ import annotations

from .cognitive_bridge import CognitiveBridge
from .events import VisionCognitionEvent

__all__ = ["CognitiveBridge", "VisionCognitionEvent"]
