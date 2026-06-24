"""
Tests for core/runtime — the heart of FRIDAY 4.0.
Covers: lifecycle, cross-thread emit (the 3.0 dead-bus regression), handler
isolation, thread-pool offload/submit, the scheduler, spawn, request/response,
and recovery after stop.
"""

import asyncio
import threading
import time

import pytest

from core.infra.friday_signal import Signal
from core.runtime import Runtime


# ── lifecycle ──────────────────────────────────────────────────────────────────
def test_start_is_idempotent(runtime):
    runtime.start()  # second call must be a no-op, not an error
    assert runtime.health()["runtime"]["loop_running"] is True
    assert runtime.health()["runtime"]["thread_alive"] is True


def test_recovery_after_stop():
    rt = Runtime(workers=1)
    rt.start()
    assert rt.health()["runtime"]["loop_running"] is True
    rt.stop()
    h = rt.health()
    assert h["runtime"]["loop_running"] is False
    assert h["runtime"]["stopped"] is True
    rt.stop()  # double stop is safe


# ── the core regression: emit from a worker thread must reach the loop ─────────
def test_cross_thread_emit_reaches_handler(runtime):
    got = []
    done = threading.Event()

    async def handler(ev):
        got.append(ev.data)
        done.set()

    runtime.on(Signal.USER_TEXT, handler)
    runtime.emit(Signal.USER_TEXT, data="hello", source="test")  # called from main thread

    assert done.wait(2.0), "handler never ran — bus is dead (3.0 regression)"
    assert got == ["hello"]
    assert runtime.health()["bus"]["handled"] >= 1


def test_handler_failure_is_isolated(runtime):
    good = threading.Event()

    async def bad(ev):
        raise RuntimeError("boom")

    async def good_handler(ev):
        good.set()

    runtime.on(Signal.USER_TEXT, bad)
    runtime.on(Signal.USER_TEXT, good_handler)
    runtime.emit(Signal.USER_TEXT, data="x")

    assert good.wait(2.0), "a failing handler killed a healthy one"
    # give the error counter a beat to settle
    time.sleep(0.05)
    assert runtime.health()["bus"]["errors"] >= 1


# ── blocking work goes through the pool, never the loop ────────────────────────
def test_offload_runs_in_pool(runtime):
    result = {}
    done = threading.Event()

    async def driver(ev):
        name = await runtime.offload(lambda: threading.current_thread().name)
        result["name"] = name
        done.set()

    runtime.on(Signal.HEARTBEAT, driver)
    runtime.emit(Signal.HEARTBEAT)

    assert done.wait(2.0)
    assert "friday-io" in result["name"], f"offload ran on {result['name']}, not the pool"


def test_submit_returns_future(runtime):
    fut = runtime.submit(lambda a, b: a + b, 2, 3)
    assert fut.result(2.0) == 5


# ── scheduler ──────────────────────────────────────────────────────────────────
def test_schedule_fires_repeatedly(runtime):
    counter = {"n": 0}
    reached = threading.Event()

    def job():
        counter["n"] += 1
        if counter["n"] >= 2:
            reached.set()

    runtime.schedule("tick", job, every=0.1)
    assert reached.wait(3.0), "scheduled job did not fire twice"
    runtime.cancel_schedule("tick")
    time.sleep(0.05)
    assert counter["n"] >= 2
    # health reflects the job's bookkeeping
    meta = runtime.health()["runtime"]["scheduled"]
    # job may already be cancelled/removed; if present it should show runs
    if "tick" in meta:
        assert meta["tick"]["runs"] >= 2


def test_async_schedule_job(runtime):
    hits = {"n": 0}
    reached = threading.Event()

    async def ajob():
        hits["n"] += 1
        reached.set()

    runtime.schedule("atick", ajob, every=0.1, run_immediately=True)
    assert reached.wait(2.0)
    runtime.cancel_schedule("atick")


# ── background coroutines ──────────────────────────────────────────────────────
def test_spawn_coroutine(runtime):
    done = threading.Event()

    async def task():
        await asyncio.sleep(0.01)
        done.set()

    runtime.spawn(task, name="t")
    assert done.wait(2.0)


# ── request/response ───────────────────────────────────────────────────────────
def test_wait_for_signal(runtime):
    def emitter():
        time.sleep(0.1)
        runtime.emit(Signal.THINKING_DONE, data="answer")

    threading.Thread(target=emitter, daemon=True).start()
    ev = runtime.wait_for(Signal.THINKING_DONE, timeout=2.0)
    assert ev is not None
    assert ev.data == "answer"


def test_wait_for_timeout_returns_none(runtime):
    ev = runtime.wait_for(Signal.SHUTDOWN, timeout=0.3)
    assert ev is None


# ── diagnostics ────────────────────────────────────────────────────────────────
def test_health_and_metrics_shape(runtime):
    h = runtime.health()
    assert set(["runtime", "bus"]).issubset(h.keys())
    m = runtime.metrics()
    assert "bus" in m and "uptime_s" in m


def test_register_health_provider(runtime):
    runtime.register_health("memory", lambda: {"vectors": 42})
    assert runtime.health()["memory"] == {"vectors": 42}


def test_health_provider_error_is_contained(runtime):
    runtime.register_health("flaky", lambda: (_ for _ in ()).throw(ValueError("nope")))
    assert "error" in runtime.health()["flaky"]
