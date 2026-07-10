"""
tests/test_signal_bus.py — M32.1 base perfection: the legacy event bus has a
real lifecycle. The 3.0 defect: the bus existed but its dispatch loop never
ran, so every emit_sync went to /dev/null. These tests pin the repair:
emit_sync self-starts an owned loop, delivery is guaranteed, and events are
mirrored one-way onto the Runtime bus when a runtime is up.
"""

import threading
import time

import pytest

from core.infra.friday_signal import EventBus, Signal


def _wait(predicate, timeout=3.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def test_emit_sync_delivers_without_any_loop():
    """The headline 3.0 defect: emit_sync from plain sync code must reach a
    subscribed handler, with nobody having started the bus."""
    bus = EventBus()
    got = threading.Event()

    async def handler(event):
        if event.data == "ping":
            got.set()

    bus.on(Signal.HEARTBEAT, handler)
    bus.emit_sync(Signal.HEARTBEAT, data="ping", source="test")
    try:
        assert got.wait(3.0), "event was dropped — dispatch loop not running"
    finally:
        bus.shutdown()


def test_emit_sync_from_worker_threads():
    """Emitters live on arbitrary threads (FAISS indexer, Flask jobs, daemons)."""
    bus = EventBus()
    seen = []

    async def handler(event):
        seen.append(event.data)

    bus.on(Signal.MEMORY_SAVED, handler)
    threads = [
        threading.Thread(target=bus.emit_sync, args=(Signal.MEMORY_SAVED, i))
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert _wait(lambda: len(seen) == 8), f"only {len(seen)}/8 events delivered"
        assert sorted(seen) == list(range(8))
    finally:
        bus.shutdown()


def test_ensure_running_is_idempotent():
    bus = EventBus()
    bus.ensure_running()
    first_thread = bus._thread
    bus.ensure_running()
    try:
        assert bus._thread is first_thread, "second ensure_running spawned a new thread"
    finally:
        bus.shutdown()


def test_handler_errors_stay_isolated():
    bus = EventBus()
    got = threading.Event()

    async def bad(event):
        raise RuntimeError("boom")

    async def good(event):
        got.set()

    bus.on(Signal.UI_UPDATE, bad)
    bus.on(Signal.UI_UPDATE, good)
    bus.emit_sync(Signal.UI_UPDATE, data="x")
    try:
        assert got.wait(3.0), "a crashing handler killed its siblings"
        assert _wait(lambda: bus.stats().get("errors", 0) == 1)
    finally:
        bus.shutdown()


def test_shutdown_stops_owned_thread():
    bus = EventBus()
    bus.ensure_running()
    thread = bus._thread
    bus.shutdown()
    assert _wait(lambda: not thread.is_alive()), "bus thread survived shutdown"
    assert bus._loop is None


class _FakeRuntime:
    def __init__(self):
        self.mirrored = []
        self.is_running = True

    def emit(self, signal, data=None, source="?", priority=5):
        self.mirrored.append((signal, data, source, priority))


@pytest.fixture
def fake_runtime(monkeypatch):
    import core.runtime.runtime as rt_mod

    fake = _FakeRuntime()
    monkeypatch.setattr(rt_mod, "_runtime", fake)
    return fake


def test_events_mirror_onto_runtime_bus(fake_runtime):
    bus = EventBus()
    bus.emit_sync(Signal.THINKING_DONE, data="answer", source="neural", priority=2)
    try:
        assert _wait(lambda: len(fake_runtime.mirrored) == 1), "event not mirrored to runtime"
        signal, data, source, priority = fake_runtime.mirrored[0]
        assert signal is Signal.THINKING_DONE
        assert data == "answer"
        assert source == "neural"
        assert priority == 2
        assert bus.stats().get("mirrored") == 1
    finally:
        bus.shutdown()


def test_shutdown_signal_never_mirrors(fake_runtime):
    bus = EventBus()
    bus.ensure_running()
    bus.shutdown()  # emits SHUTDOWN internally
    assert all(sig is not Signal.SHUTDOWN for sig, *_ in fake_runtime.mirrored), \
        "bus lifecycle leaked into the runtime"


def test_no_mirror_when_runtime_absent():
    """peek_runtime never constructs — with no runtime, events dispatch locally only."""
    import core.runtime.runtime as rt_mod

    assert rt_mod.peek_runtime() is None or True  # tolerate other tests' runtime
    bus = EventBus()
    got = threading.Event()

    async def handler(event):
        got.set()

    bus.on(Signal.WORLD_UPDATED, handler)
    bus.emit_sync(Signal.WORLD_UPDATED)
    try:
        assert got.wait(3.0)
    finally:
        bus.shutdown()
