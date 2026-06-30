"""
core/services/plugin_service.py — FRIDAY V3 (M16)
PluginService — the extension registry. New capabilities (camera adapters, relationship
rules, room classifiers, future detectors) register a factory under a `(kind, name)` and
are resolved by name — so the system extends without modifying core logic. Pure registry;
no I/O.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional


class PluginService:
    name = "plugin"

    def __init__(self) -> None:
        self._plugins: dict[str, dict[str, Callable]] = {}
        self._lock = threading.Lock()

    def register(self, kind: str, name: str, factory: Callable) -> None:
        with self._lock:
            self._plugins.setdefault(kind, {})[name] = factory

    def get(self, kind: str, name: str) -> Optional[Callable]:
        with self._lock:
            return self._plugins.get(kind, {}).get(name)

    def list(self, kind: str) -> list:
        with self._lock:
            return sorted(self._plugins.get(kind, {}))

    def kinds(self) -> list:
        with self._lock:
            return sorted(self._plugins)

    def health(self) -> dict:
        with self._lock:
            return {"status": "ok",
                    "plugins": {k: len(v) for k, v in self._plugins.items()}}
