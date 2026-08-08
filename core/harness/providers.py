"""
core/harness/providers.py — FRIDAY harness (provider abstraction)

The provider-independent model interface. Every intelligence source FRIDAY can
call — the local builtin model team, a cloud frontier model, a coding model, a
vision model, a future backend that does not exist yet — is reachable through
ONE contract: `ModelProvider`. The harness (registry, orchestrator, verifier)
depends only on this interface, never on a vendor SDK or a specific HTTP shape,
so provider-specific logic lives in exactly one adapter and a new backend is
added by writing a single class.

Boundaries (why this is safe):
    · A provider does pure generation. It receives a `GenRequest` (task, prompt,
      read-only context, decoding params) and returns a `GenResult`. It holds no
      reference to FRIDAY's stores, services, or secrets beyond its own transport
      credentials — it cannot modify memory/goals, execute skills, or read the
      DecisionLog.
    · A provider MUST NOT raise for an operational failure. `BaseProvider.generate`
      converts any exception into `GenResult(ok=False, error=...)`, so one bad
      backend can never crash a turn — a failure is data the harness routes around.
    · The interface is async so the orchestrator can run providers concurrently
      (Phase 4 parallel agents / verification); sync backends (the local model
      team, a `requests`-based cloud client) adapt trivially with
      `asyncio.to_thread`, mirroring the existing `IntelligenceOS.think_async`.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


class Capability(str, Enum):
    """What a provider can do. Kept deliberately small and provider-facing; the
    richer `TaskType` taxonomy lives one layer down in the Intelligence OS."""
    TEXT = "text"
    REASONING = "reasoning"
    CODE = "code"
    PLANNING = "planning"
    VISION = "vision"
    OCR = "ocr"
    SPEECH = "speech"
    EMBEDDING = "embedding"


def as_capability(value) -> str:
    """Normalise a Capability | str to its string value (routing keys are strings)."""
    return value.value if isinstance(value, Capability) else str(value)


@dataclass
class ProviderInfo:
    """Everything the registry needs to route to a provider without calling it."""
    name: str
    kind: str = "local"                       # "local" | "cloud"
    model: str = ""
    capabilities: frozenset = field(default_factory=frozenset)
    context_length: int = 4096
    # Relative cost/preference hint for routing: 0.0 = free (local), higher =
    # pricier/slower cloud. The registry prefers the cheapest capable provider.
    cost_hint: float = 0.0

    def supports(self, cap) -> bool:
        return as_capability(cap) in self.capabilities

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["capabilities"] = sorted(self.capabilities)
        return d


@dataclass
class GenRequest:
    """A single generation request. `context` is read-only primitives only — a
    provider never receives live FRIDAY objects."""
    prompt: str = ""
    task: str = Capability.TEXT.value
    context: dict = field(default_factory=dict)
    system: str = ""
    max_tokens: int = 512
    temperature: float = 0.3
    trace_id: str = field(default_factory=new_trace_id)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class GenResult:
    """The uniform result every provider returns — success or failure. `ok=False`
    with a populated `error` is the honest failure the harness routes around."""
    provider: str
    ok: bool = True
    text: str = ""
    model: str = ""
    confidence: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    error: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


class ModelProvider(ABC):
    """The contract every backend implements. Prefer subclassing `BaseProvider`,
    which supplies the never-raise / latency-timing wrapper for free."""

    info: ProviderInfo

    @abstractmethod
    async def generate(self, request: GenRequest) -> GenResult:
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        ...

    def capabilities(self) -> frozenset:
        return self.info.capabilities

    def available(self) -> bool:
        """Cheap, synchronous readiness check (e.g. key present, model loaded).
        The registry uses it to skip a provider before spending a call."""
        return True


class BaseProvider(ModelProvider):
    """Convenience base: wraps a subclass's `_generate` with exception-guarding
    and latency timing so no provider can raise or forget to time itself."""

    def __init__(self, info: ProviderInfo) -> None:
        self.info = info

    async def generate(self, request: GenRequest) -> GenResult:
        t0 = time.perf_counter()
        try:
            result = await self._generate(request)
        except Exception as e:  # noqa: BLE001 — a backend failure is data, not a crash
            return GenResult(provider=self.info.name, ok=False, error=str(e),
                             model=self.info.model,
                             latency_ms=(time.perf_counter() - t0) * 1000.0)
        if result.latency_ms == 0.0:
            result.latency_ms = (time.perf_counter() - t0) * 1000.0
        if not result.provider:
            result.provider = self.info.name
        return result

    async def _generate(self, request: GenRequest) -> GenResult:  # pragma: no cover
        raise NotImplementedError

    async def health_check(self) -> dict:
        return {"name": self.info.name, "kind": self.info.kind,
                "status": "ok" if self.available() else "unavailable",
                "capabilities": sorted(self.info.capabilities)}


def make_info(name: str, capabilities: Iterable, *, kind: str = "local",
              model: str = "", context_length: int = 4096,
              cost_hint: float = 0.0) -> ProviderInfo:
    """Small helper so adapters declare capabilities as Capability | str freely."""
    caps = frozenset(as_capability(c) for c in capabilities)
    return ProviderInfo(name=name, kind=kind, model=model, capabilities=caps,
                        context_length=context_length, cost_hint=cost_hint)
