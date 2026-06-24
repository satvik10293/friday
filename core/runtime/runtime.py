"""
core/runtime/runtime.py — FRIDAY 4.0
The Runtime. The heart of FRIDAY.

One event loop on a dedicated thread, one thread-pool for blocking work, one
scheduler, one health/metrics surface. It exists to end the 3.0 pathology where
an async bus was created but never run and `emit_sync` could not reliably reach
it from worker threads.

Hard rules this enforces:
  • There is exactly one event loop, and it is always running while the runtime is up.
  • No subsystem may create unmanaged threads — use spawn()/offload()/submit()/schedule().
  • Every emit is thread-safe (bridged onto the loop via run_coroutine_threadsafe).
  • Everything is observable via health() and metrics().

Public API
  start(timeout) / stop(timeout)        lifecycle (idempotent)
  on(signal, handler) / off(...)        subscribe (async handlers)
  emit(signal, ...)                     thread-safe publish (any thread)
  emit_async(signal, ...)               publish from inside the loop
  wait_for(signal, timeout)             request/response (blocks caller thread)
  spawn(coro|coro_fn, name)             managed background coroutine
  submit(fn, *a, **kw) -> Future        run blocking fn in the pool (sync caller)
  offload(fn, *a, **kw) -> awaitable    run blocking fn in the pool (from the loop)
  schedule(name, fn, every, ...)        runtime-managed periodic job
  cancel_schedule(name)
  register_health(name, provider)
  health() / metrics()

Import is side-effect free: get_runtime() constructs but does NOT start.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

from core.infra.friday_signal import Signal
from .bus import AsyncEventBus

log = logging.getLogger("friday.runtime")


class Runtime:
    def __init__(self, workers: int = 4, name: str = "friday-runtime") -> None:
        self._bus = AsyncEventBus()
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="friday-io")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._thread_main, name=name, daemon=True)
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._started = False
        self._started_at: Optional[float] = None
        self._lock = threading.Lock()

        self._bg_tasks: set[asyncio.Task] = set()
        self._scheduled: dict[str, asyncio.Task] = {}
        self._sched_meta: dict[str, dict] = {}
        self._health_providers: dict[str, Callable[[], Any]] = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self, timeout: float = 10.0) -> "Runtime":
        with self._lock:
            if self._started:
                return self
            self._started = True
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("Runtime failed to become ready within timeout")
        self._started_at = time.time()
        log.info("Runtime online (workers=%d)", self._pool._max_workers)
        return self

    def _thread_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._startup())
        try:
            self._loop.run_forever()
        finally:
            try:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            except Exception:
                pass
            self._loop.close()

    async def _startup(self) -> None:
        await self._bus.start()
        self._ready.set()

    def stop(self, timeout: float = 10.0) -> None:
        with self._lock:
            if not self._started or self._stopped.is_set():
                return

        async def _shutdown() -> None:
            for t in list(self._scheduled.values()):
                t.cancel()
            for t in list(self._bg_tasks):
                t.cancel()
            await self._bus.stop()

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop).result(timeout)
        except Exception:
            log.warning("Runtime shutdown did not complete cleanly", exc_info=True)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout)
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._stopped.set()
        log.info("Runtime stopped")

    # ── events ─────────────────────────────────────────────────────────────────
    def on(self, signal: Signal, handler) -> None:
        self._bus.on(signal, handler)

    def off(self, signal: Signal, handler) -> None:
        self._bus.off(signal, handler)

    def emit(self, signal: Signal, data=None, source: str = "runtime", priority: int = 5) -> Future:
        """Thread-safe publish from ANY thread. Returns a concurrent.futures.Future
        (fire-and-forget — you normally ignore it)."""
        return asyncio.run_coroutine_threadsafe(
            self._bus.emit(signal, data, source, priority), self._loop)

    async def emit_async(self, signal: Signal, data=None, source: str = "runtime", priority: int = 5) -> None:
        """Publish from inside the loop (e.g. from a handler)."""
        await self._bus.emit(signal, data, source, priority)

    def submit_coro(self, coro) -> Future:
        """Schedule a coroutine on the loop from any thread and return a
        concurrent.futures.Future carrying its result/exception. Unlike spawn()
        (which supervises and swallows exceptions for fire-and-forget background
        work), this propagates the result — use it when you need the value back."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def wait_for(self, signal: Signal, timeout: float = 10.0):
        """Block the *calling thread* until `signal` fires (or timeout)."""
        fut = asyncio.run_coroutine_threadsafe(self._bus.wait_for(signal, timeout), self._loop)
        return fut.result(timeout + 1.0)

    # ── work submission ─────────────────────────────────────────────────────────
    def spawn(self, coro, name: Optional[str] = None) -> Future:
        """Schedule a managed background coroutine from any thread."""
        if callable(coro) and not asyncio.iscoroutine(coro):
            coro = coro()
        if not asyncio.iscoroutine(coro):
            raise TypeError("spawn() expects a coroutine or zero-arg coroutine function")
        return asyncio.run_coroutine_threadsafe(self._supervise(coro, name), self._loop)

    async def _supervise(self, coro, name: Optional[str]) -> Any:
        task = asyncio.current_task()
        if task is not None:
            self._bg_tasks.add(task)
        try:
            return await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("background task %r crashed", name)
        finally:
            if task is not None:
                self._bg_tasks.discard(task)

    def submit(self, fn: Callable, *args, **kwargs) -> Future:
        """Run a blocking fn in the thread pool. For SYNC callers."""
        return self._pool.submit(fn, *args, **kwargs)

    async def offload(self, fn: Callable, *args, **kwargs) -> Any:
        """Run a blocking fn in the thread pool. For callers INSIDE the loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._pool, functools.partial(fn, *args, **kwargs))

    # ── scheduler ───────────────────────────────────────────────────────────────
    def schedule(self, name: str, fn: Callable, every: float,
                 jitter: float = 0.0, run_immediately: bool = False) -> None:
        """Register a runtime-managed periodic job. `fn` may be sync or async;
        sync jobs run in the thread pool so they never block the loop."""
        async def _runner() -> None:
            if run_immediately:
                await self._invoke(fn, name)
            while True:
                delay = every + (random.uniform(0.0, jitter) if jitter else 0.0)
                await asyncio.sleep(max(0.0, delay))
                await self._invoke(fn, name)

        def _install() -> None:
            old = self._scheduled.get(name)
            if old:
                old.cancel()
            self._scheduled[name] = self._loop.create_task(_runner(), name=f"sched:{name}")
            self._sched_meta[name] = {"every": every, "runs": 0, "errors": 0, "last_run": None}

        self._loop.call_soon_threadsafe(_install)

    async def _invoke(self, fn: Callable, name: str) -> None:
        try:
            if asyncio.iscoroutinefunction(fn):
                await fn()
            else:
                await self.offload(fn)
            meta = self._sched_meta.get(name)
            if meta:
                meta["runs"] += 1
                meta["last_run"] = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            meta = self._sched_meta.get(name)
            if meta:
                meta["errors"] += 1
            log.exception("scheduled job %r failed", name)

    def cancel_schedule(self, name: str) -> None:
        def _cancel() -> None:
            t = self._scheduled.pop(name, None)
            if t:
                t.cancel()
            self._sched_meta.pop(name, None)
        self._loop.call_soon_threadsafe(_cancel)

    # ── diagnostics ────────────────────────────────────────────────────────────
    def register_health(self, name: str, provider: Callable[[], Any]) -> None:
        self._health_providers[name] = provider

    def health(self) -> dict:
        uptime = (time.time() - self._started_at) if self._started_at else 0.0
        h = {
            "runtime": {
                "started": self._started,
                "stopped": self._stopped.is_set(),
                "loop_running": self._loop.is_running(),
                "thread_alive": self._thread.is_alive(),
                "uptime_s": round(uptime, 1),
                "background_tasks": len(self._bg_tasks),
                "scheduled": dict(self._sched_meta),
                "pool_max_workers": self._pool._max_workers,
            },
            "bus": self._bus.stats(),
        }
        for name, provider in list(self._health_providers.items()):
            try:
                h[name] = provider()
            except Exception as e:
                h[name] = {"error": str(e)}
        return h

    def metrics(self) -> dict:
        return {
            "bus": self._bus.stats(),
            "scheduled_jobs": len(self._scheduled),
            "background_tasks": len(self._bg_tasks),
            "uptime_s": round((time.time() - self._started_at), 1) if self._started_at else 0.0,
        }


# ── singleton ───────────────────────────────────────────────────────────────────
_runtime: Optional[Runtime] = None
_runtime_lock = threading.Lock()


def get_runtime() -> Runtime:
    """Get the global runtime (constructed lazily, NOT started)."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = Runtime()
    return _runtime


def start_runtime(**kwargs) -> Runtime:
    rt = get_runtime()
    rt.start(**kwargs)
    return rt


def stop_runtime() -> None:
    global _runtime
    if _runtime is not None:
        _runtime.stop()
