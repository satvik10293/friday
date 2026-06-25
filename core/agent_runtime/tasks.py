"""
core/agent_runtime/tasks.py — FRIDAY 4.0 (M10)
Reference, picklable agent task functions. Because they live at module scope in an
importable package, they cross the process boundary cleanly (Windows `spawn`),
which makes the runtime usable and testable without flaky test-module pickling.
M11 agents will provide their own importable targets the same way.
"""

from __future__ import annotations

import time


def echo(value):
    return value


def square(n):
    return n * n


def slow(seconds: float, value=None):
    time.sleep(seconds)
    return value


def boom(message: str = "agent failed"):
    raise RuntimeError(message)


def cpu_spin(iterations: int = 100_000) -> int:
    total = 0
    for i in range(iterations):
        total += i * i
    return total
