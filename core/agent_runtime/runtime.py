"""
core/agent_runtime/runtime.py — FRIDAY 4.0 (M10)
The process-based agent runtime. Runs an agent's work in a separate OS process so
CPU-bound agents run truly in parallel (no GIL contention) and a crashing agent
cannot take FRIDAY down. Collects per-run lifecycle metrics and aggregates them.

Lifecycle:  spawn process → perform work → return result → terminate process.

Resilience: if the OS can't spawn a process (sandbox, platform limits), the runtime
degrades to isolated in-process execution and reports `mode="in_process"` rather
than failing.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import time
import traceback
from typing import Callable, Optional

from .models import AgentResult, AgentSpec, RuntimeMetrics

log = logging.getLogger("friday.agent_runtime")


def _worker(target: Callable, args: tuple, kwargs: dict, q) -> None:
    """Child-process entry point. Runs the target and reports outcome + the child's
    own CPU time and RSS back through the queue."""
    cpu0 = time.process_time()
    try:
        value = target(*args, **(kwargs or {}))
        cpu_ms = (time.process_time() - cpu0) * 1000.0
        q.put(("ok", value, cpu_ms, _rss_mb()))
    except Exception as e:  # noqa: BLE001 — report any failure to the parent
        cpu_ms = (time.process_time() - cpu0) * 1000.0
        q.put(("err", f"{e}\n{traceback.format_exc()}", cpu_ms, _rss_mb()))


def _rss_mb() -> float:
    try:
        import psutil
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


class ProcessAgentRuntime:
    def __init__(self, *, default_timeout: float = 30.0, use_processes: bool = True) -> None:
        self.default_timeout = default_timeout
        self._use_processes = use_processes
        self.metrics = RuntimeMetrics()
        try:
            self._ctx = mp.get_context("spawn")
        except (ValueError, RuntimeError):
            self._ctx = None
            self._use_processes = False

    # ── public ──────────────────────────────────────────────────────────────────
    def run(self, target, *args, name: str = "", timeout: Optional[float] = None,
            **kwargs) -> AgentResult:
        spec = AgentSpec(name=name or getattr(target, "__name__", "agent"),
                         target=target, args=args, kwargs=kwargs,
                         timeout=timeout if timeout is not None else self.default_timeout)
        return self.run_spec(spec)

    def run_spec(self, spec: AgentSpec) -> AgentResult:
        if self._use_processes and self._ctx is not None:
            result = self._run_process(spec)
        else:
            result = self._run_in_process(spec)
        self.metrics.record(result)
        return result

    # ── process execution ───────────────────────────────────────────────────────
    def _run_process(self, spec: AgentSpec) -> AgentResult:
        q = self._ctx.Queue()
        proc = self._ctx.Process(target=_worker,
                                 args=(spec.target, spec.args, spec.kwargs, q),
                                 name=f"friday-agent-{spec.name}")
        t_launch = time.perf_counter()
        try:
            proc.start()
        except Exception as e:   # spawning unavailable → degrade gracefully
            log.warning("process spawn failed (%s); running in-process", e)
            return self._run_in_process(spec)
        spawn_ms = (time.perf_counter() - t_launch) * 1000.0

        payload = None
        try:
            payload = q.get(timeout=spec.timeout)
        except Exception:
            payload = None        # timeout or queue error
        proc.join(timeout=1.0)
        timed_out = payload is None and proc.is_alive()
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2.0)
        lifetime_ms = (time.perf_counter() - t_launch) * 1000.0

        result = AgentResult(name=spec.name, ok=False, pid=proc.pid,
                             spawn_ms=spawn_ms, lifetime_ms=lifetime_ms,
                             exit_code=proc.exitcode, mode="process")
        if timed_out:
            result.timed_out = True
            result.error = f"timed out after {spec.timeout}s"
            return result
        if payload is None:
            result.error = f"no result (exit code {proc.exitcode})"
            return result
        status, value, cpu_ms, rss = payload
        result.cpu_ms = cpu_ms
        result.peak_memory_mb = rss
        if status == "ok":
            result.ok = True
            result.value = value
        else:
            result.error = value
        return result

    # ── in-process fallback (isolated try/except) ───────────────────────────────
    def _run_in_process(self, spec: AgentSpec) -> AgentResult:
        t0 = time.perf_counter()
        cpu0 = time.process_time()
        result = AgentResult(name=spec.name, ok=False, mode="in_process")
        try:
            result.value = spec.target(*spec.args, **(spec.kwargs or {}))
            result.ok = True
        except Exception as e:  # noqa: BLE001
            result.error = f"{e}\n{traceback.format_exc()}"
        result.cpu_ms = (time.process_time() - cpu0) * 1000.0
        result.lifetime_ms = (time.perf_counter() - t0) * 1000.0
        result.peak_memory_mb = _rss_mb()
        return result

    # ── diagnostics ─────────────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return self.metrics.snapshot()

    def health(self) -> dict:
        return {"status": "ok", "mode": "process" if self._use_processes else "in_process",
                **self.metrics.snapshot()}


_runtime: Optional[ProcessAgentRuntime] = None


def get_agent_runtime() -> ProcessAgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ProcessAgentRuntime()
    return _runtime
