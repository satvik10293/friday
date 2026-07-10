"""
core/runtime — FRIDAY 4.0 runtime layer.

The heart of FRIDAY: one event loop, one thread pool, one scheduler, one
health/metrics surface. Import is side-effect free — nothing starts until you
call start().

    from core.runtime import get_runtime
    rt = get_runtime()
    rt.start()
"""

from .bus import AsyncEventBus
from .runtime import Runtime, get_runtime, peek_runtime, start_runtime, stop_runtime

__all__ = [
    "AsyncEventBus",
    "Runtime",
    "get_runtime",
    "peek_runtime",
    "start_runtime",
    "stop_runtime",
]
