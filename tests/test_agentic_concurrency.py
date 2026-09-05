"""
"Many tasks at once" (concurrency): the agentic workflow can work several SAFE
goals in parallel, while anything needing approval stays on a single serial lane
(the approval path is not reentrant). Default max_concurrency=1 is byte-for-byte
today's serial behaviour. These pin real parallelism, the safety lane, the claim
set, and the no-runtime fallback.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from core.executive.agentic import AgenticWorkflow
from core.skills.permissions import Permission
from tests.test_agentic_workflow import _Executor, _Goal, _Goals, _Skill


class _Runtime:
    """Minimal runtime double: submit() onto a real thread pool."""

    def __init__(self, workers=8):
        self._pool = ThreadPoolExecutor(max_workers=workers)

    def submit(self, fn, *a, **k):
        return self._pool.submit(fn, *a, **k)


def _peak_recorder(wf, hold=0.05):
    state = {"cur": 0, "peak": 0}
    lock = threading.Lock()

    def rec(goal_id, executive=None):
        with lock:
            state["cur"] += 1
            state["peak"] = max(state["peak"], state["cur"])
        time.sleep(hold)
        with lock:
            state["cur"] -= 1
        return "completed"

    wf._work_goal = rec
    return state


def test_default_is_serial_peak_one():
    goals = _Goals([_Goal(f"g{i}", "think") for i in range(4)])
    wf = AgenticWorkflow(goals, None, goals_per_cycle=4)     # max_concurrency=1 default
    state = _peak_recorder(wf)
    wf.cycle()
    assert state["peak"] == 1                                # one at a time


def test_safe_goals_run_concurrently():
    goals = _Goals([_Goal(f"g{i}", "think") for i in range(3)])   # no skill = SAFE
    wf = AgenticWorkflow(goals, None, goals_per_cycle=3,
                         runtime=_Runtime(), max_concurrency=3)
    barrier = threading.Barrier(3, timeout=5)
    reached = []

    def rec(goal_id, executive=None):
        barrier.wait()          # returns ONLY if all three arrive together
        reached.append(goal_id)
        return "completed"

    wf._work_goal = rec
    summary = wf.cycle()
    assert sorted(reached) == ["g0", "g1", "g2"]             # met at the barrier => parallel
    assert sorted(summary["completed"]) == ["g0", "g1", "g2"]


def test_each_concurrent_worker_gets_its_own_executive():
    goals = _Goals([_Goal(f"g{i}", "think") for i in range(3)])
    wf = AgenticWorkflow(goals, None, goals_per_cycle=3,
                         runtime=_Runtime(), max_concurrency=3)
    seen = []
    lock = threading.Lock()

    def rec(goal_id, executive=None):
        with lock:
            seen.append(id(executive))
        return "completed"

    wf._work_goal = rec
    wf.cycle()
    assert len(seen) == 3
    assert len(set(seen)) == 3 and None not in seen         # a distinct brain each


def test_approval_goals_stay_serial_even_with_concurrency():
    ex = _Executor({"shell.run": _Skill(Permission.ADMIN_ONLY)})
    goals = _Goals([_Goal(f"g{i}", "danger", skill="shell.run") for i in range(3)])
    wf = AgenticWorkflow(goals, ex, goals_per_cycle=3,
                         runtime=_Runtime(), max_concurrency=3)
    state = _peak_recorder(wf)
    wf.cycle()
    assert state["peak"] == 1                                # above-SAFE never parallel


def test_no_runtime_forces_serial():
    goals = _Goals([_Goal(f"g{i}", "think") for i in range(3)])
    wf = AgenticWorkflow(goals, None, goals_per_cycle=3,
                         runtime=None, max_concurrency=3)
    state = _peak_recorder(wf)
    wf.cycle()
    assert state["peak"] == 1


def test_inflight_claim_prevents_double_work():
    wf = AgenticWorkflow(_Goals([]), None, goals_per_cycle=5)
    assert wf._claim("g1") is True
    assert wf._claim("g1") is False            # already being worked
    wf._release(["g1"])
    assert wf._claim("g1") is True             # freed → claimable again


def test_max_concurrency_capped_by_goals_per_cycle():
    wf = AgenticWorkflow(_Goals([]), None, goals_per_cycle=2, max_concurrency=5)
    assert wf._max_concurrency == 2            # never fan out wider than the cycle bound
