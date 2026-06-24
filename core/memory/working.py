"""
core/memory/working.py — FRIDAY 4.0
Working memory: a small, bounded, in-RAM attention buffer of what's happening
*right now*. Distinct from durable episodic storage — this is the "current task"
window the cognitive layer reasons over. Lost on restart by design.
"""

from __future__ import annotations

from collections import deque


class WorkingMemory:
    def __init__(self, capacity: int = 20) -> None:
        self._buf: deque = deque(maxlen=capacity)
        self.capacity = capacity

    def add(self, item: dict) -> None:
        self._buf.append(item)

    def snapshot(self) -> list[dict]:
        return list(self._buf)

    def recent(self, n: int) -> list[dict]:
        return list(self._buf)[-n:]

    def clear(self) -> None:
        self._buf.clear()

    def __len__(self) -> int:
        return len(self._buf)
