"""
core/intelligence/base.py — FRIDAY 4.0 (M12)
Foundations of the Intelligence Operating System: the task taxonomy, the local
`Model` protocol every model plugin implements, and the request/result/metadata
dataclasses the whole layer speaks in.

Local-first by construction: a model receives only an `InferenceRequest` (task,
prompt, a read-only context dict, and decoding params). It holds no references to
FRIDAY's stores or services, so a model can never modify memory/goals/knowledge,
execute commands, or read secrets — state changes flow only through the secure
service APIs the IOS calls itself (Part 18).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class TaskType(str, Enum):
    CODING = "coding"
    PLANNING = "planning"
    WRITING = "writing"
    RESEARCH = "research"
    VISION = "vision"
    SPEECH = "speech"
    OCR = "ocr"
    MEMORY_RETRIEVAL = "memory_retrieval"
    MATH = "math"
    SCIENTIFIC = "scientific"
    SIMULATION = "simulation"
    AGENT_COORDINATION = "agent_coordination"
    AUTOMATION = "automation"
    WEB = "web"
    ROBOTICS = "robotics"
    GENERAL = "general"


class Complexity(str, Enum):
    TRIVIAL = "trivial"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class ModelStatus(str, Enum):
    REGISTERED = "registered"
    LOADED = "loaded"
    UNLOADED = "unloaded"
    UNHEALTHY = "unhealthy"
    FAILED = "failed"


@dataclass
class ModelInfo:
    """Everything the registry tracks about a model (Part 2)."""
    name: str
    version: str = "1.0"
    author: str = "friday"
    capabilities: set = field(default_factory=set)        # set[TaskType value]
    languages: list = field(default_factory=lambda: ["en"])
    context_length: int = 2048
    ram_mb: float = 0.0
    vram_mb: float = 0.0
    disk_mb: float = 0.0
    avg_speed_ms: float = 0.0
    avg_accuracy: float = 0.0
    reliability: float = 1.0
    supported_tasks: list = field(default_factory=list)
    health: str = "ok"
    status: str = ModelStatus.REGISTERED.value
    installed_at: float = field(default_factory=time.time)
    benchmark_scores: dict = field(default_factory=dict)
    last_update: float = field(default_factory=time.time)
    is_local: bool = True
    is_cloud: bool = False

    def supports(self, task: str) -> bool:
        return task in self.capabilities or TaskType.GENERAL.value in self.capabilities

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["capabilities"] = sorted(self.capabilities)
        return d


@dataclass
class InferenceRequest:
    task: str = TaskType.GENERAL.value
    prompt: str = ""
    context: dict = field(default_factory=dict)           # read-only, primitives only
    max_tokens: int = 512
    temperature: float = 0.3
    trace_id: str = field(default_factory=new_id)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class InferenceResult:
    model: str
    ok: bool = True
    text: str = ""
    structured: dict = field(default_factory=dict)
    confidence: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@runtime_checkable
class Model(Protocol):
    """The plugin contract every local (or cloud) model implements. Pure inference:
    no side effects, no service access."""
    info: ModelInfo
    def infer(self, request: InferenceRequest) -> InferenceResult: ...
    def health(self) -> dict: ...
    def load(self) -> None: ...
    def unload(self) -> None: ...


class BaseModel:
    """Convenience base: lifecycle no-ops + latency-timed `infer` wrapper. Subclasses
    implement `_run(request) -> (text, structured, confidence)`."""

    def __init__(self, info: ModelInfo) -> None:
        self.info = info
        self._loaded = False

    def load(self) -> None:
        self._loaded = True
        self.info.status = ModelStatus.LOADED.value

    def unload(self) -> None:
        self._loaded = False
        self.info.status = ModelStatus.UNLOADED.value

    @property
    def loaded(self) -> bool:
        return self._loaded

    def health(self) -> dict:
        return {"status": self.info.health, "loaded": self._loaded,
                "name": self.info.name}

    def infer(self, request: InferenceRequest) -> InferenceResult:
        if not self._loaded:
            self.load()
        t0 = time.perf_counter()
        try:
            text, structured, confidence = self._run(request)
            latency = (time.perf_counter() - t0) * 1000.0
            return InferenceResult(model=self.info.name, ok=True, text=text,
                                   structured=structured, confidence=confidence,
                                   latency_ms=latency, tokens=len(text.split()))
        except Exception as e:  # noqa: BLE001 — a model failure is data, not a crash
            latency = (time.perf_counter() - t0) * 1000.0
            return InferenceResult(model=self.info.name, ok=False, error=str(e),
                                   latency_ms=latency)

    def _run(self, request: InferenceRequest):  # pragma: no cover - overridden
        raise NotImplementedError
