"""
core/runtime/bus.py — FRIDAY 4.0
Loop-safe async event bus. Unlike the legacy core/infra/friday_signal.EventBus
(whose PriorityQueue was created at import time on whatever loop happened to be
current — the root cause of the "dead bus" in 3.0), this bus creates its queue
lazily *inside* the runtime loop, so every emit/dispatch is bound to one loop.

It reuses the Signal taxonomy and Event dataclass from the legacy module so the
vocabulary is preserved during the strangler-fig migration.

Ownership:    Runtime (core/runtime/runtime.py) owns the only instance.
Lifecycle:    start() / stop() are awaited *on the runtime loop*.
Thread-model: emit() is awaited on the loop; cross-thread emits go through
              Runtime.emit() which bridges via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable, Optional

from core.infra.friday_signal import Signal, Event   # preserve the 3.0 taxonomy

log = logging.getLogger("friday.runtime.bus")

Handler = Callable[[Event], Awaitable[None]]


class AsyncEventBus:
    """Priority pub/sub with isolated, concurrent handler dispatch."""

    def __init__(self) -> None:
        self._subs: dict[Signal, list[Handler]] = defaultdict(list)
        self._queue: Optional[asyncio.PriorityQueue] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._seq = 0
        self._stats: dict[str, int] = defaultdict(int)

    # ── queue (created lazily on the owning loop) ──────────────────────────────
    def _q(self) -> asyncio.PriorityQueue:
        if self._queue is None:
            self._queue = asyncio.PriorityQueue()
        return self._queue

    # ── subscribe ──────────────────────────────────────────────────────────────
    def on(self, signal: Signal, handler: Handler) -> Handler:
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"handler for {signal} must be async def, got {handler!r}")
        self._subs[signal].append(handler)
        return handler

    def off(self, signal: Signal, handler: Handler) -> None:
        try:
            self._subs[signal].remove(handler)
        except ValueError:
            pass

    # ── publish ────────────────────────────────────────────────────────────────
    async def emit(self, signal: Signal, data=None, source: str = "?", priority: int = 5) -> None:
        self._seq += 1
        ev = Event(signal=signal, data=data, source=source, priority=priority)
        # (priority, seq, ev): seq breaks ties so two equal-priority events never
        # force a comparison of Event objects.
        self._q().put_nowait((priority, self._seq, ev))
        self._stats["emitted"] += 1

    # ── lifecycle ──────────────────────────────────────────────────────────────
    async def start(self) -> None:
        self._q()
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="bus-dispatch")
        log.debug("bus dispatch loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
        log.debug("bus stopped | stats=%s", dict(self._stats))

    # ── dispatch ───────────────────────────────────────────────────────────────
    async def _run(self) -> None:
        q = self._q()
        while self._running:
            try:
                _, _, ev = await asyncio.wait_for(q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            try:
                await self._dispatch(ev)
            finally:
                q.task_done()

    async def _dispatch(self, ev: Event) -> None:
        handlers = list(self._subs.get(ev.signal, []))   # copy: safe under concurrent on()
        if not handlers:
            self._stats["unhandled"] += 1
            return

        async def _safe(h: Handler) -> None:
            try:
                await h(ev)
                self._stats["handled"] += 1
            except Exception:                              # one bad handler never kills others
                self._stats["errors"] += 1
                log.exception("handler %r failed on %s",
                              getattr(h, "__name__", h), ev.signal.name)

        await asyncio.gather(*[_safe(h) for h in handlers])

    # ── request/response ───────────────────────────────────────────────────────
    async def wait_for(self, signal: Signal, timeout: float = 10.0) -> Optional[Event]:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        async def _capture(ev: Event) -> None:
            if not fut.done():
                fut.set_result(ev)

        self.on(signal, _capture)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.off(signal, _capture)

    # ── diagnostics ────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        d = dict(self._stats)
        d["queue_size"] = self._queue.qsize() if self._queue else 0
        d["subscriptions"] = sum(len(v) for v in self._subs.values())
        d["running"] = self._running
        return d
