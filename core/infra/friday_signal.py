"""
friday_signal.py — Friday 3.0
The Nervous System. Async event bus.
Every module publishes here. Every module listens here.
Nothing is hardwired. Nothing blocks.
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Coroutine, Optional
from collections import defaultdict

log = logging.getLogger("friday.signal")


# ── Event Types ───────────────────────────────────────────────────────────────

class Signal(Enum):
    # ── Input signals
    USER_VOICE          = auto()   # raw voice input received
    USER_TEXT           = auto()   # text input received
    WAKE_WORD           = auto()   # wake word detected
    SCREEN_CHANGED      = auto()   # screen content changed
    CLIPBOARD_CHANGED   = auto()   # clipboard updated

    # ── Brain signals
    INTENT_CLASSIFIED   = auto()   # empath classified intent/tone
    CONTEXT_READY       = auto()   # chronicle + world context assembled
    THINKING_START      = auto()   # neural started reasoning
    THINKING_DONE       = auto()   # neural produced response
    CODEX_ACTIVATED     = auto()   # codex specialist engaged
    KNOWLEDGE_EXTRACTED = auto()   # sovereign extracted facts from response

    # ── Memory signals
    MEMORY_SAVED        = auto()   # chronicle persisted a turn
    MEMORY_RECALLED     = auto()   # chronicle returned relevant context
    WORLD_UPDATED       = auto()   # world module indexed new knowledge

    # ── Mood signals
    MOOD_UPDATED        = auto()   # psyche updated emotional state
    TONE_DETECTED       = auto()   # empath detected Satvik's tone

    # ── Expression signals
    SPEAK_START         = auto()   # voice started speaking
    SPEAK_DONE          = auto()   # voice finished speaking
    UI_UPDATE           = auto()   # face should update display
    UI_MODE             = auto()   # data: str voice|text
    ACTION_EXECUTE      = auto()   # action module should run a command

    # ── System signals
    MODULE_READY        = auto()   # a module finished initializing
    MODULE_ERROR        = auto()   # a module hit a critical error
    SHUTDOWN            = auto()   # clean shutdown requested
    HEARTBEAT           = auto()   # periodic alive ping


# ── Event ─────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    signal:    Signal
    data:      Any             = None
    source:    str             = "unknown"
    timestamp: float           = field(default_factory=time.time)
    priority:  int             = 5          # 1 = highest, 10 = lowest
    id:        int             = field(default_factory=lambda: Event._next_id())

    _counter: int = 0

    @staticmethod
    def _next_id() -> int:
        Event._counter += 1
        return Event._counter

    def __lt__(self, other: "Event") -> bool:
        # Priority queue: lower number = higher priority
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.timestamp < other.timestamp


# ── Handler types ─────────────────────────────────────────────────────────────

Handler = Callable[[Event], Coroutine]   # async def handler(event: Event)


# ── EventBus ──────────────────────────────────────────────────────────────────

class EventBus:
    """
    Async publish-subscribe event bus.
    - Async handlers run concurrently per event.
    - Priority queue ensures critical signals aren't starved.
    - Dead-letter log for unhandled events (debug mode).
    - Handler errors are isolated — one bad handler never kills others.
    """

    def __init__(self, queue_size: int = 256):
        self._subscribers: dict[Signal, list[Handler]] = defaultdict(list)
        self._wildcard:    list[Handler]                = []
        self._queue_size:  int                          = queue_size
        self._queue:       Optional[asyncio.PriorityQueue] = None
        self._running:     bool                         = False
        self._task:        Optional[asyncio.Task]       = None
        self._stats:       dict[str, int]               = defaultdict(int)
        self._loop:        Optional[asyncio.AbstractEventLoop] = None
        self._thread:      Optional[threading.Thread]   = None
        self._lifecycle_lock                            = threading.Lock()

    def _q(self) -> asyncio.PriorityQueue:
        # Created lazily so the queue binds to the loop that actually runs the
        # bus, never to whatever loop happened to be current at import time
        # (the root cause of the 3.0 dead bus).
        if self._queue is None:
            self._queue = asyncio.PriorityQueue(maxsize=self._queue_size)
        return self._queue

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def on(self, signal: Signal, handler: Handler) -> None:
        """Subscribe an async handler to a specific signal."""
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"Handler must be async: {handler.__name__}")
        self._subscribers[signal].append(handler)
        log.debug("Subscribed %s → %s", signal.name, handler.__name__)

    def on_any(self, handler: Handler) -> None:
        """Subscribe to ALL signals (wildcard). Use sparingly."""
        if not asyncio.iscoroutinefunction(handler):
            raise TypeError(f"Wildcard handler must be async: {handler.__name__}")
        self._wildcard.append(handler)

    def off(self, signal: Signal, handler: Handler) -> None:
        """Unsubscribe a handler."""
        try:
            self._subscribers[signal].remove(handler)
        except ValueError:
            pass

    # ── Publish ───────────────────────────────────────────────────────────────

    async def emit(
        self,
        signal:   Signal,
        data:     Any    = None,
        source:   str    = "unknown",
        priority: int    = 5,
    ) -> None:
        """Publish an event. Non-blocking — drops to queue."""
        event = Event(signal=signal, data=data, source=source, priority=priority)
        self._mirror_to_runtime(signal, data, source, priority)
        try:
            self._q().put_nowait((priority, event))
            self._stats["emitted"] += 1
            log.debug("→ %s from %s (p%d)", getattr(signal, "name", signal), source, priority)
        except asyncio.QueueFull:
            log.warning("Event bus full — dropped %s from %s", getattr(signal, "name", signal), source)
            self._stats["dropped"] += 1

    def emit_sync(self, signal: Signal, data: Any = None, source: str = "unknown", priority: int = 5) -> None:
        """
        Fire-and-forget from sync code, from any thread.
        Delivery is guaranteed: the owned dispatch loop is started on first use
        and the emit is bridged onto it via run_coroutine_threadsafe. Never
        spins throwaway loops (the 3.0 behaviour that dropped every event).
        """
        try:
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is not None and running is self._loop:
                # Already on the bus loop (e.g. a handler re-emitting).
                running.create_task(self.emit(signal, data, source, priority))
                return
            self.ensure_running()
            if self._loop is None:
                raise RuntimeError("bus dispatch loop unavailable")
            asyncio.run_coroutine_threadsafe(
                self.emit(signal, data, source, priority), self._loop)
        except Exception as e:
            log.error("Signal failed for %s: %s", getattr(signal, "name", signal), e)

    def _mirror_to_runtime(self, signal: Signal, data: Any, source: str, priority: int) -> None:
        """
        One-way mirror onto the 4.0 Runtime bus so legacy emitters reach the
        live nervous system when the runtime is up. Never constructs a runtime;
        no echo risk (the runtime bus never mirrors back). SHUTDOWN stays local
        — this bus's lifecycle must not leak into the runtime's.
        """
        if signal is Signal.SHUTDOWN:
            return
        try:
            from core.runtime.runtime import peek_runtime
            rt = peek_runtime()
            if rt is not None and rt.is_running:
                rt.emit(signal, data, source, priority)
                self._stats["mirrored"] += 1
        except Exception:
            log.debug("runtime mirror failed", exc_info=True)

    # ── Dispatch loop ─────────────────────────────────────────────────────────

    async def _dispatch(self, event: Event) -> None:
        """Run all handlers for this event concurrently. Isolate failures."""
        handlers = list(self._subscribers.get(event.signal, []))
        handlers += self._wildcard

        if not handlers:
            self._stats["unhandled"] += 1
            log.debug("No handlers for %s", event.signal.name)
            return

        async def _safe_call(h: Handler) -> None:
            try:
                await h(event)
                self._stats["handled"] += 1
            except Exception as e:
                self._stats["errors"] += 1
                log.error("Handler %s crashed on %s: %s", h.__name__, event.signal.name, e)

        await asyncio.gather(*[_safe_call(h) for h in handlers])

    async def _run_loop(self) -> None:
        """Main dispatch loop. Runs until SHUTDOWN signal."""
        log.info("Signal bus online")
        while self._running:
            try:
                _, event = await asyncio.wait_for(self._q().get(), timeout=1.0)
                if event.signal == Signal.SHUTDOWN:
                    log.info("Signal bus received SHUTDOWN")
                    self._running = False
                    await self._dispatch(event)
                    break
                await self._dispatch(event)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                log.error("Bus loop error: %s", e)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the dispatch loop on the caller's (already running) loop."""
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.ensure_future(self._run_loop())
        log.info("EventBus started")

    def ensure_running(self) -> None:
        """
        Start the dispatch loop on an owned daemon thread. Idempotent and
        thread-safe. After this returns, emitted events are guaranteed a
        consumer — the 3.0 defect was a bus that could exist without ever
        running, silently dropping everything.
        """
        with self._lifecycle_lock:
            if self._running and self._loop is not None and self._loop.is_running():
                return
            self._running = True
            self._queue = None          # rebind fresh on the new loop
            ready = threading.Event()

            def _main() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._task = loop.create_task(self._run_loop())
                ready.set()
                try:
                    loop.run_forever()
                finally:
                    loop.close()

            self._thread = threading.Thread(target=_main, name="friday-signal-bus", daemon=True)
            self._thread.start()
            if not ready.wait(5.0):
                log.error("Signal bus thread failed to start")

    async def stop(self) -> None:
        """Graceful shutdown."""
        await self.emit(Signal.SHUTDOWN, source="bus")
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except asyncio.TimeoutError:
                self._task.cancel()
        log.info("EventBus stopped | stats: %s", dict(self._stats))

    def shutdown(self, timeout: float = 3.0) -> None:
        """Sync counterpart of stop() for the owned-thread lifecycle."""
        loop, thread = self._loop, self._thread
        if loop is None or not loop.is_running():
            self._running = False
            return
        try:
            asyncio.run_coroutine_threadsafe(self.stop(), loop).result(timeout)
        except Exception:
            log.warning("bus shutdown did not complete cleanly")
        if thread is not None and thread is not threading.current_thread():
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout)
        self._loop = None
        self._thread = None

    # ── Utilities ─────────────────────────────────────────────────────────────

    async def wait_for(
        self,
        signal:  Signal,
        timeout: float = 10.0,
    ) -> Optional[Event]:
        """
        Block until a specific signal arrives or timeout.
        Useful for request/response patterns between modules.
        """
        future: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _capture(event: Event) -> None:
            if not future.done():
                future.set_result(event)

        self.on(signal, _capture)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            self.off(signal, _capture)

    def stats(self) -> dict:
        return dict(self._stats)


# ── Global singleton ──────────────────────────────────────────────────────────

_bus: Optional[EventBus] = None


def get_bus() -> EventBus:
    """Get or create the global event bus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


def ensure_bus() -> EventBus:
    """Get the global bus with its dispatch loop guaranteed running."""
    bus = get_bus()
    bus.ensure_running()
    return bus


async def start_bus() -> EventBus:
    """Start the global bus. Call once at boot."""
    bus = get_bus()
    await bus.start()
    return bus


async def stop_bus() -> None:
    """Stop the global bus. Call at shutdown."""
    global _bus
    if _bus:
        await _bus.stop()
        _bus = None


# ── Convenience decorators ────────────────────────────────────────────────────

def listen(signal: Signal):
    """
    Decorator to auto-register a handler on the global bus.

    Usage:
        @listen(Signal.USER_TEXT)
        async def handle_text(event: Event):
            print(event.data)
    """
    def decorator(fn: Handler) -> Handler:
        get_bus().on(signal, fn)
        return fn
    return decorator


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s [%(name)s] %(message)s")

    async def _test():
        bus = await start_bus()

        received = []

        @listen(Signal.USER_TEXT)
        async def on_text(event: Event):
            received.append(event.data)
            print(f"  OK Received USER_TEXT: '{event.data}' from '{event.source}'")

        @listen(Signal.THINKING_DONE)
        async def on_response(event: Event):
            print(f"  OK Received THINKING_DONE: '{event.data}'")

        print("\n[friday_signal] Running self-test...\n")

        await bus.emit(Signal.USER_TEXT,     data="Hello Friday",      source="ears",   priority=2)
        await bus.emit(Signal.THINKING_DONE, data="Hey Satvik, what's up?", source="neural", priority=2)
        await bus.emit(Signal.MOOD_UPDATED,  data={"mood": "curious"}, source="psyche", priority=5)

        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0] == "Hello Friday"

        print(f"\n  Stats: {bus.stats()}")
        print("\n[friday_signal] All tests passed OK\n")

        await stop_bus()

    asyncio.run(_test())
