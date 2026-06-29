"""
core/vision/ — FRIDAY 6.1 (M14) Vision System.

The complete visual-perception subsystem. Every camera frame is moved into the
Cognitive OS as a rich `Frame` (Transport), perceived by a modular processing pipeline,
standardized into a `core.perception.Observation` (Observation Builder), and routed
through Attention → Perception → Entity Resolver → World Model (Cognitive Bridge) while
the Scene Graph and Visual Memory retain what was seen. Vision is a perception
subsystem only: it builds observations and never reasons or writes the World Model
directly.

The pipeline:
    Reality → Camera → Vision Transport → Camera Manager → Frame →
    Processing Pipeline → Observation Builder → Cognitive Bridge
    (Attention → Entity Resolver → Persistent Entity IDs → World Model) →
    Scene Graph + Visual Memory

`VisionSystem` (service.py) is the single facade. Side-effect-free to import — nothing
starts, no camera opens, no socket binds, no model loads at import time.
"""

from __future__ import annotations

from .config import VisionConfig
from .service import VisionSystem, get_vision_system
from .transport.frame import Frame, FrameFlags, PixelFormat
from .transport.manager import CameraManager
from .transport.service import VisionTransport, get_vision_transport

__all__ = [
    "VisionSystem", "get_vision_system", "VisionConfig",
    "VisionTransport", "get_vision_transport", "CameraManager",
    "Frame", "PixelFormat", "FrameFlags",
]
