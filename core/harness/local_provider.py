"""
core/harness/local_provider.py — FRIDAY harness (local adapter)

Makes FRIDAY's own mind a provider behind the same interface as any cloud model.
It wraps the Intelligence OS (`IntelligenceOS.think`) so the harness can route,
retry, verify, and fall back over local and cloud backends uniformly — the
local-first default (free, private, always available) sitting at the front of
every fallback chain.

Import-safe: the Intelligence OS (which loads the local model team) is resolved
lazily on first call, never at import time, so wiring the harness costs nothing
until a local generation is actually requested.
"""

from __future__ import annotations

import asyncio

from .providers import (BaseProvider, Capability, GenRequest, GenResult,
                        make_info)


class LocalProvider(BaseProvider):
    """Adapter over the Intelligence OS. Pass an `ios` for tests/DI, or leave it
    None to lazily resolve the process-wide singleton on first use."""

    def __init__(self, ios=None, *, name: str = "local-intelligence") -> None:
        super().__init__(make_info(
            name,
            (Capability.TEXT, Capability.REASONING, Capability.CODE,
             Capability.PLANNING),
            kind="local", model="friday-local", context_length=2048,
            cost_hint=0.0))          # free → always preferred when capable
        self._ios = ios

    def _resolve_ios(self):
        if self._ios is None:
            from core.intelligence.service import get_intelligence_os
            self._ios = get_intelligence_os()
        return self._ios

    def available(self) -> bool:
        # The local mind is always available; if construction fails the harness
        # still records the failure via generate()'s never-raise wrapper.
        return True

    async def _generate(self, request: GenRequest) -> GenResult:
        return await asyncio.to_thread(self._blocking, request)

    def _blocking(self, request: GenRequest) -> GenResult:
        ios = self._resolve_ios()
        task = request.task if request.task in _KNOWN_TASKS else None
        resp = ios.think(request.prompt, task=task, context=dict(request.context))
        return GenResult(
            provider=self.info.name, ok=bool(getattr(resp, "ok", True)),
            text=getattr(resp, "answer", "") or "", model="friday-local",
            confidence=float(getattr(resp, "confidence", 0.0) or 0.0),
            latency_ms=float(getattr(resp, "latency_ms", 0.0) or 0.0),
            error=getattr(resp, "error", "") or "",
            meta={"kind": "local", "trace_id": getattr(resp, "trace_id", ""),
                  "models_used": list(getattr(resp, "models_used", []) or [])})


# Task strings the Intelligence OS understands; anything else is passed as None
# so the router classifies it itself (harness Capabilities are coarser).
_KNOWN_TASKS = {
    "coding", "planning", "writing", "research", "vision", "speech", "ocr",
    "memory_retrieval", "math", "scientific", "simulation", "agent_coordination",
    "automation", "web", "robotics", "general",
}
