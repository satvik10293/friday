"""
core/vision/processing/registry.py — FRIDAY 6.1 (M14)
The processor registry: maps a processor name → a zero-arg factory, so the pipeline
is assembled by name from config and new processors plug in without touching the
pipeline. Adding a vision capability = register a factory.
"""

from __future__ import annotations

from typing import Callable, Optional

from .base import VisionProcessor

ProcessorFactory = Callable[[], VisionProcessor]


class ProcessorRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, ProcessorFactory] = {}

    def register(self, name: str, factory: ProcessorFactory) -> None:
        self._factories[name] = factory

    def create(self, name: str) -> Optional[VisionProcessor]:
        factory = self._factories.get(name)
        return factory() if factory is not None else None

    def names(self) -> list[str]:
        return sorted(self._factories)

    def __contains__(self, name: str) -> bool:
        return name in self._factories


def default_registry(config=None) -> ProcessorRegistry:
    """Build a registry of all built-in processors, bound to a ProcessingConfig.
    Imported lazily so registering never imports heavy backends."""
    from .scene_stats import SceneStatsProcessor
    from .motion import MotionDetector
    from .segmentation import SegmentationProcessor
    from .tracking import ObjectTracker
    from .objects import ObjectDetector
    from .face import FaceDetector, FaceRecognitionProcessor
    from .ocr import OCRProcessor
    from .pose import PoseEstimator

    reg = ProcessorRegistry()
    reg.register("scene_stats", lambda: SceneStatsProcessor())
    reg.register("motion", lambda: MotionDetector(config))
    reg.register("segmentation", lambda: SegmentationProcessor(config))
    reg.register("tracking", lambda: ObjectTracker(config))
    reg.register("objects", lambda: ObjectDetector(config))
    reg.register("face", lambda: FaceDetector(config))
    reg.register("face_recognition", lambda: FaceRecognitionProcessor(config))
    reg.register("ocr", lambda: OCRProcessor(config))
    reg.register("pose", lambda: PoseEstimator(config))
    return reg
