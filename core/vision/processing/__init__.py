"""
core/vision/processing/ — FRIDAY 6.1 (M14) Vision Processing Pipeline.

A modular pipeline of independent processor plugins that turn a `Frame` into labelled
detections + structured data. Processors perform perception only — they never build
Observations, resolve entities, or touch the World Model. Adding a capability means
adding a plugin + registering a factory; the pipeline is unchanged.

Side-effect-free to import: heavy backends are imported lazily inside processors.
"""

from __future__ import annotations

from .base import (BoundingBox, Detection, ProcessingResult, ProcessorResult,
                   VisionProcessor)
from .pipeline import VisionPipeline
from .registry import ProcessorRegistry, default_registry

__all__ = ["VisionProcessor", "Detection", "BoundingBox", "ProcessorResult",
           "ProcessingResult", "VisionPipeline", "ProcessorRegistry", "default_registry"]
