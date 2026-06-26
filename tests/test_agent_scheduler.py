"""M11 — Agent scheduler: parallel dispatch of worker subtasks."""

from core.agent_runtime import ProcessAgentRuntime
from core.society.models import SubTask
from core.society.scheduler import AgentScheduler


def _sched(use_processes=False, max_parallel=4):
    return AgentScheduler(ProcessAgentRuntime(use_processes=use_processes),
                          max_parallel=max_parallel)


def test_dispatch_single():
    s = _sched()
    res = s.dispatch([SubTask(template="Math Solver", target="math_solve", args=("2+2",))])
    assert len(res) == 1 and res[0].ok and res[0].value["value"] == 4


def test_dispatch_parallel():
    s = _sched(max_parallel=4)
    subs = [SubTask(template="Math Solver", target="math_solve", args=(f"{i}+{i}",))
            for i in range(5)]
    res = s.dispatch(subs)
    assert len(res) == 5
    assert all(r.ok for r in res)
    assert [r.value["value"] for r in res] == [0, 2, 4, 6, 8]   # order preserved


def test_dispatch_empty():
    assert _sched().dispatch([]) == []


def test_unknown_target_fails_gracefully():
    s = _sched()
    res = s.dispatch([SubTask(template="Ghost", target="does_not_exist")])
    assert not res[0].ok and "unknown worker target" in res[0].error


def test_failure_isolated_among_successes():
    s = _sched(max_parallel=3)
    subs = [
        SubTask(template="Math Solver", target="math_solve", args=("1+1",)),
        SubTask(template="Math Solver", target="math_solve", args=("bad!!!",)),  # raises
        SubTask(template="Math Solver", target="math_solve", args=("3+3",)),
    ]
    res = s.dispatch(subs)
    assert res[0].ok and res[2].ok
    assert not res[1].ok                      # one failure does not sink the batch


def test_metrics_collected():
    s = _sched()
    s.dispatch([SubTask(template="Math Solver", target="math_solve", args=("2+2",))])
    snap = s.runtime.snapshot()
    assert snap["spawns"] >= 1


def test_real_process_dispatch():
    s = _sched(use_processes=True, max_parallel=2)
    res = s.dispatch([SubTask(template="Math Solver", target="math_solve", args=("6*7",)),
                      SubTask(template="Math Solver", target="math_solve", args=("5*5",))])
    assert res[0].value["value"] == 42 and res[1].value["value"] == 25
    assert all(r.mode == "process" for r in res)
