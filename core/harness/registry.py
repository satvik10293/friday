"""
core/harness/registry.py — FRIDAY harness (provider registry + routing)

Registration and capability-based discovery for providers. The registry answers
one question the orchestrator asks constantly: "given this task, which backends
can do it, healthiest and cheapest first?" It owns one `CircuitBreaker` per
provider so reliability state travels with the backend, and it never itself
calls a provider — selection is pure metadata, so routing stays O(providers).

Selection order for a capability:
    1. available() and breaker not open  (usable right now)
    2. lower cost_hint                    (prefer free/local over paid cloud)
    3. registration order                 (stable, predictable fallback chain)

Providers that are unavailable or whose breaker is open are still returned, but
last — so the orchestrator can fall back to them if every preferred one fails.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from .providers import ModelProvider, as_capability
from .reliability import CircuitBreaker


@dataclass
class _Entry:
    provider: ModelProvider
    breaker: CircuitBreaker
    order: int


class ProviderRegistry:
    def __init__(self, *, fail_threshold: int = 3, reset_timeout_s: float = 30.0) -> None:
        self._entries: dict[str, _Entry] = {}
        self._fail_threshold = fail_threshold
        self._reset_timeout_s = reset_timeout_s
        self._counter = 0
        self._lock = threading.RLock()

    # ── registration ─────────────────────────────────────────────────────────────
    def register(self, provider: ModelProvider, *,
                 breaker: Optional[CircuitBreaker] = None) -> ModelProvider:
        with self._lock:
            name = provider.info.name
            self._entries[name] = _Entry(
                provider=provider,
                breaker=breaker or CircuitBreaker(fail_threshold=self._fail_threshold,
                                                  reset_timeout_s=self._reset_timeout_s),
                order=self._counter)
            self._counter += 1
        return provider

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._entries.pop(name, None) is not None

    def has(self, name: str) -> bool:
        return name in self._entries

    # ── lookup ───────────────────────────────────────────────────────────────────
    def get(self, name: str) -> Optional[ModelProvider]:
        entry = self._entries.get(name)
        return entry.provider if entry else None

    def breaker_for(self, name: str) -> Optional[CircuitBreaker]:
        entry = self._entries.get(name)
        return entry.breaker if entry else None

    def all(self) -> list[ModelProvider]:
        with self._lock:
            return [e.provider for e in sorted(self._entries.values(), key=lambda e: e.order)]

    def by_capability(self, capability) -> list[ModelProvider]:
        """All providers that declare `capability`, best-first (see module docstring)."""
        cap = as_capability(capability)
        with self._lock:
            entries = [e for e in self._entries.values() if e.provider.info.supports(cap)]

        def rank(e: _Entry):
            usable = e.provider.available() and e.breaker.allow()
            return (0 if usable else 1, e.provider.info.cost_hint, e.order)

        return [e.provider for e in sorted(entries, key=rank)]

    def best_for(self, capability) -> Optional[ModelProvider]:
        cands = self.by_capability(capability)
        return cands[0] if cands else None

    # ── observability ────────────────────────────────────────────────────────────
    def status(self) -> dict:
        with self._lock:
            return {name: {"info": e.provider.info.to_dict(),
                           "available": e.provider.available(),
                           "breaker": e.breaker.to_dict()}
                    for name, e in self._entries.items()}
