"""
core/intelligence/ — FRIDAY 4.0 (M12) Intelligence Operating System.

FRIDAY's permanent, local-first intelligence backbone. A model-agnostic router +
registry route every request to a *team* of collaborating local models (no single
model dominates), with reasoning strategies, a critic, confidence estimation,
reflection, learning, traces, health monitoring, benchmarks, caching, and
optimisation. FRIDAY never depends on external AI for her primary intelligence;
cloud models are opt-in plugins behind the same `Model` protocol.

Security boundary (Part 18): models receive only a read-only context dict + prompt —
never service/store references — so they can't modify memory/goals/knowledge,
execute commands, or read secrets. State changes flow only through the secure
service APIs the IOS calls itself.

Side-effect-free to import.
"""

from __future__ import annotations

from .base import (BaseModel, Complexity, InferenceRequest, InferenceResult, Model,
                   ModelInfo, ModelStatus, TaskType)
from .confidence_engine import ConfidenceBreakdown, ConfidenceEngine
from .critic import CriticEngine, CriticReport
from .reasoning_engine import ReasoningEngine, ReasoningResult, ReasoningStrategy
from .registry import IntelligenceRegistry
from .router import IntelligenceRouter, RouterResponse
from .service import IntelligenceOS, get_intelligence_os

__all__ = [
    "IntelligenceOS", "get_intelligence_os", "IntelligenceRouter", "RouterResponse",
    "IntelligenceRegistry", "ReasoningEngine", "ReasoningResult", "ReasoningStrategy",
    "ConfidenceEngine", "ConfidenceBreakdown", "CriticEngine", "CriticReport",
    "Model", "BaseModel", "ModelInfo", "ModelStatus", "InferenceRequest",
    "InferenceResult", "TaskType", "Complexity",
]
