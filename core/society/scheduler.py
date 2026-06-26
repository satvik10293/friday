"""
core/society/scheduler.py — FRIDAY 4.0 (M11)
Schedules worker subtasks for parallel execution. Each subtask runs through the
M10 ProcessAgentRuntime (separate process by default), dispatched concurrently up
to a resource cap. Resolves a subtask's target *name* to its picklable function so
it can cross the process boundary.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from core.agent_runtime import ProcessAgentRuntime
from . import worker_tasks
from .models import SubTask, WorkerResult


class AgentScheduler:
    def __init__(self, runtime: Optional[ProcessAgentRuntime] = None, *,
                 max_parallel: int = 4) -> None:
        self._runtime = runtime if runtime is not None else ProcessAgentRuntime()
        self.max_parallel = max_parallel

    @property
    def runtime(self) -> ProcessAgentRuntime:
        return self._runtime

    def _run_one(self, st: SubTask) -> WorkerResult:
        target = getattr(worker_tasks, st.target, None)
        if target is None:
            return WorkerResult(subtask_id=st.id, template=st.template, ok=False,
                                error=f"unknown worker target: {st.target}")
        t0 = time.perf_counter()
        res = self._runtime.run(target, *st.args, name=st.template, **st.kwargs)
        wall = (time.perf_counter() - t0) * 1000.0
        return WorkerResult(subtask_id=st.id, template=st.template, ok=res.ok,
                            value=res.value, error=res.error,
                            duration_ms=res.lifetime_ms or wall, cpu_ms=res.cpu_ms,
                            mode=res.mode)

    def dispatch(self, subtasks: list[SubTask]) -> list[WorkerResult]:
        """Run all subtasks in parallel (bounded by max_parallel)."""
        if not subtasks:
            return []
        if len(subtasks) == 1:
            return [self._run_one(subtasks[0])]
        results: list[WorkerResult] = [None] * len(subtasks)  # type: ignore
        with ThreadPoolExecutor(max_workers=min(self.max_parallel, len(subtasks))) as ex:
            futures = {ex.submit(self._run_one, st): i for i, st in enumerate(subtasks)}
            for fut, i in futures.items():
                results[i] = fut.result()
        return results
