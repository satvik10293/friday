"""
core/intelligence/cache.py — FRIDAY 4.0 (M12)
The intelligence cache (Part 14). A bounded, thread-safe LRU cache that prevents
repeated computation — reasoning results, embeddings, knowledge lookups, model
outputs — keyed by a stable hash of the inputs. Tracks hit/miss stats for the
optimizer and Mission Control.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from typing import Any, Callable, Optional


def cache_key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class IntelligenceCache:
    def __init__(self, capacity: int = 1024) -> None:
        self.capacity = capacity
        self._data: "OrderedDict[str, Any]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = compute()
        self.put(key, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def resize(self, capacity: int) -> None:
        with self._lock:
            self.capacity = max(1, capacity)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {"size": len(self._data), "capacity": self.capacity,
                    "hits": self.hits, "misses": self.misses,
                    "hit_rate": round(self.hits / total, 4) if total else 0.0}

    def __len__(self) -> int:
        return len(self._data)
