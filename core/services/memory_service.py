"""
core/services/memory_service.py — FRIDAY V3 (M16)
MemoryService — durable long-term memory / Chronicle sink behind a stable API. It adapts
whatever memory backend is injected (the M2 `MemoryService`, the legacy Chronicle module,
or any object exposing a remember/record/recall surface) via duck typing, and keeps a
small bounded local history so `recall` and tests work even with no backend.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Optional

log = logging.getLogger("friday.services.memory")


class MemoryService:
    name = "memory"

    def __init__(self, backend=None, *, history: int = 1000) -> None:
        self._backend = backend
        self._local: deque = deque(maxlen=history)
        self._writes = 0

    def remember(self, content: str, *, kind: str = "event",
                 metadata: Optional[dict] = None) -> None:
        self._local.append({"content": content, "kind": kind,
                            "metadata": metadata or {}, "ts": time.time()})
        self._writes += 1
        if self._backend is None:
            return
        # adapt to common backend signatures (M2 MemoryService / Chronicle / generic)
        try:
            if hasattr(self._backend, "remember"):
                try:
                    self._backend.remember("system", content, topic=kind,
                                           metadata=metadata or {})   # M2 signature
                    return
                except TypeError:
                    self._backend.remember(content)                   # generic
                    return
            for m in ("record", "save_fact", "add", "log_event"):
                fn = getattr(self._backend, m, None)
                if callable(fn):
                    fn(content)
                    return
        except Exception:  # noqa: BLE001 — a memory failure must never break the caller
            log.debug("memory backend write failed", exc_info=True)

    def recall(self, query: str, *, limit: int = 8) -> list:
        if self._backend is not None and hasattr(self._backend, "recall"):
            try:
                return list(self._backend.recall(query, k=limit))
            except Exception:  # noqa: BLE001
                log.debug("memory backend recall failed", exc_info=True)
        q = (query or "").lower()
        hits = [m for m in self._local if q in m["content"].lower()]
        return hits[-limit:][::-1]

    def health(self) -> dict:
        return {"status": "ok", "backend": type(self._backend).__name__ if self._backend
                else "local_only", "writes": self._writes}
