"""
core/services/runtime_service.py — FRIDAY V3 (M16)
RuntimeService — the decoupled event bus + health registration seam. Publishers and
subscribers never know about each other: a publisher calls `publish(event, data)`, and
the service delivers to local subscribers synchronously AND (when a real M1 Runtime is
injected) forwards to the async runtime bus for Mission Control. With no runtime it runs
a self-contained in-process bus, so spatial cognition is fully testable without booting
the runtime. A bounded event history backs observability.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

log = logging.getLogger("friday.services.runtime")


class RuntimeService:
    name = "runtime"

    def __init__(self, runtime=None, *, history: int = 500) -> None:
        self._runtime = runtime
        self._subs: dict[str, list[Callable]] = {}
        self._history: deque = deque(maxlen=history)
        self._lock = threading.Lock()
        self._published = 0

    @staticmethod
    def _key(event: Any) -> str:
        return event.value if hasattr(event, "value") else str(event)

    def publish(self, event: Any, data: Optional[dict] = None, *, source: str = "spatial") -> None:
        key = self._key(event)
        payload = data or {}
        with self._lock:
            handlers = list(self._subs.get(key, []))
            self._history.append({"event": key, "data": payload, "source": source,
                                  "ts": time.time()})
            self._published += 1
        for h in handlers:                       # local synchronous delivery
            try:
                h({"event": key, "data": payload, "source": source})
            except Exception:  # noqa: BLE001 — a bad subscriber never breaks publishing
                log.debug("subscriber failed for %s", key, exc_info=True)
        if self._runtime is not None:            # forward to the async runtime bus
            try:
                self._runtime.emit(event, data=payload, source=source)
            except Exception:  # noqa: BLE001
                log.debug("runtime emit failed for %s", key, exc_info=True)

    def subscribe(self, event: Any, handler: Callable) -> None:
        key = self._key(event)
        with self._lock:
            self._subs.setdefault(key, []).append(handler)

    def register_health(self, name: str, provider: Callable[[], Any]) -> None:
        if self._runtime is not None and hasattr(self._runtime, "register_health"):
            try:
                self._runtime.register_health(name, provider)
            except Exception:  # noqa: BLE001
                log.debug("register_health failed", exc_info=True)

    def recent(self, limit: int = 50, *, event: Optional[str] = None) -> list:
        with self._lock:
            items = list(self._history)
        if event:
            items = [e for e in items if e["event"] == event]
        return items[-limit:][::-1]

    def health(self) -> dict:
        return {"status": "ok", "runtime_attached": self._runtime is not None,
                "published": self._published,
                "subscriptions": sum(len(v) for v in self._subs.values())}
