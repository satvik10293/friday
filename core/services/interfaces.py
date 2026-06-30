"""
core/services/interfaces.py — FRIDAY V3 (M16)
The service contracts. Beginning with M16, subsystems communicate ONLY through these
stable, documented service interfaces — never by importing another subsystem's internal
implementation. Each interface is a `typing.Protocol`, so any object that structurally
satisfies it (a real wrapper, a mock, or a future remote proxy) can be injected.

Every service also satisfies `ServiceProtocol` (a `name` + `health()`), giving a uniform
surface for discovery, health aggregation, and dependency injection. No I/O here; pure
interface definitions, side-effect-free to import.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, runtime_checkable


@runtime_checkable
class ServiceProtocol(Protocol):
    """Base contract every service satisfies."""
    name: str

    def health(self) -> dict: ...


@runtime_checkable
class RuntimeServiceProtocol(ServiceProtocol, Protocol):
    """Event bus + health registration. Decouples publishers from subscribers."""
    def publish(self, event: Any, data: Optional[dict] = None, *, source: str = "?") -> None: ...
    def subscribe(self, event: Any, handler: Callable) -> None: ...
    def register_health(self, name: str, provider: Callable[[], Any]) -> None: ...


@runtime_checkable
class WorldModelServiceProtocol(ServiceProtocol, Protocol):
    """Persistent model of reality (entities + relationships)."""
    def observe(self, kind: str, name: str, *, state: Optional[dict] = None,
                attributes: Optional[dict] = None, confidence: float = 1.0) -> Optional[str]: ...
    def relate(self, source: str, target: str, relation: str, *,
               weight: float = 1.0, metadata: Optional[dict] = None) -> None: ...
    def get(self, entity_id: str) -> Optional[dict]: ...


@runtime_checkable
class MemoryServiceProtocol(ServiceProtocol, Protocol):
    """Durable long-term memory / Chronicle sink."""
    def remember(self, content: str, *, kind: str = "event",
                 metadata: Optional[dict] = None) -> None: ...
    def recall(self, query: str, *, limit: int = 8) -> list: ...


@runtime_checkable
class AttentionServiceProtocol(ServiceProtocol, Protocol):
    """Salience ranking."""
    def rank(self, items: list) -> list: ...


@runtime_checkable
class VisionServiceProtocol(ServiceProtocol, Protocol):
    """Source of visual observations (decoupled from vision internals)."""
    def detect(self) -> list: ...                     # -> list[SpatialObservation-like dict]
    def cameras(self) -> list: ...


@runtime_checkable
class AudioServiceProtocol(ServiceProtocol, Protocol):
    """Source of auditory cues (for localization / presence)."""
    def recent_events(self, *, limit: int = 20) -> list: ...


@runtime_checkable
class SpatialServiceProtocol(ServiceProtocol, Protocol):
    """Spatial cognition: scene graph, tracking, relationships, rooms, queries."""
    def update_scene(self, observations: list, *, camera_id: str = "",
                     room: Optional[str] = None) -> dict: ...
    def query(self, intent: str, **params) -> dict: ...
    def snapshot(self) -> dict: ...


@runtime_checkable
class ExecutiveServiceProtocol(ServiceProtocol, Protocol):
    """Executive brain notifications (one-way; spatial never deliberates)."""
    def notify(self, payload: dict) -> None: ...


@runtime_checkable
class ConfigurationServiceProtocol(ServiceProtocol, Protocol):
    """Configuration provider — no hardcoded values anywhere else."""
    def get(self, path: str, default: Any = None) -> Any: ...
    def section(self, name: str) -> dict: ...


@runtime_checkable
class PluginServiceProtocol(ServiceProtocol, Protocol):
    """Extension registry (camera adapters, relationship rules, future plugins)."""
    def register(self, kind: str, name: str, factory: Callable) -> None: ...
    def get(self, kind: str, name: str) -> Optional[Callable]: ...
    def list(self, kind: str) -> list: ...


@runtime_checkable
class LearningServiceProtocol(ServiceProtocol, Protocol):
    """Placeholder for M17+ learning — records experience for later training."""
    def record(self, kind: str, data: dict) -> None: ...


@runtime_checkable
class EmotionServiceProtocol(ServiceProtocol, Protocol):
    """Placeholder for affect — nudged by salient events."""
    def nudge(self, signal: dict) -> None: ...


@runtime_checkable
class PerceptionServiceProtocol(ServiceProtocol, Protocol):
    """M17 Perception Hub: the unified multimodal gateway. Ingests per-modality
    observations, fuses them into one unified observation, reasons, maintains context +
    timeline, and is the component that forwards unified understanding to the World
    Model."""
    def ingest(self, observations: list, *, session_id: str = "") -> dict: ...
    def perceive(self) -> dict: ...
    def situation(self) -> dict: ...
    def context(self) -> dict: ...
    def timeline(self, *, scope: str = "recent", **params) -> list: ...


# Canonical service names used as keys in the ServiceContainer.
class ServiceName:
    RUNTIME = "runtime"
    WORLD_MODEL = "world_model"
    MEMORY = "memory"
    ATTENTION = "attention"
    VISION = "vision"
    AUDIO = "audio"
    SPATIAL = "spatial"
    PERCEPTION = "perception"
    EXECUTIVE = "executive"
    CONFIGURATION = "configuration"
    PLUGIN = "plugin"
    LEARNING = "learning"
    EMOTION = "emotion"

    ALL = ("runtime", "world_model", "memory", "attention", "vision", "audio",
           "spatial", "perception", "executive", "configuration", "plugin",
           "learning", "emotion")
