"""M10 — Process-based agent runtime (M11 prep)."""

from core.agent_runtime import ProcessAgentRuntime, get_agent_runtime
from core.agent_runtime import tasks


# ── real subprocess execution ─────────────────────────────────────────────────────
def test_runs_in_separate_process():
    rt = ProcessAgentRuntime(default_timeout=20)
    res = rt.run(tasks.square, 6, name="sq")
    assert res.ok and res.value == 36
    assert res.mode == "process"
    assert res.pid is not None
    assert res.lifetime_ms >= 0


def test_echo_value():
    rt = ProcessAgentRuntime(default_timeout=20)
    res = rt.run(tasks.echo, {"hello": "world"})
    assert res.ok and res.value == {"hello": "world"}


def test_agent_failure_isolated():
    rt = ProcessAgentRuntime(default_timeout=20)
    res = rt.run(tasks.boom, "kaboom", name="boom")
    assert not res.ok
    assert "kaboom" in res.error
    # the parent process is obviously still alive to make this assertion
    assert res.exit_code is not None


def test_timeout_terminates():
    rt = ProcessAgentRuntime(default_timeout=20)
    res = rt.run(tasks.slow, 5.0, "late", timeout=0.5)
    assert res.timed_out and not res.ok


def test_metrics_aggregate():
    rt = ProcessAgentRuntime(default_timeout=20)
    rt.run(tasks.square, 2)
    rt.run(tasks.square, 3)
    rt.run(tasks.boom)
    snap = rt.snapshot()
    assert snap["spawns"] == 3
    assert snap["completions"] == 2 and snap["failures"] == 1
    assert 0.0 <= snap["completion_rate"] <= 1.0


def test_lifecycle_metrics_present():
    rt = ProcessAgentRuntime(default_timeout=20)
    res = rt.run(tasks.cpu_spin, 50000)
    assert res.ok
    assert res.cpu_ms >= 0.0 and res.spawn_ms >= 0.0


# ── in-process fallback (resilience) ──────────────────────────────────────────────
def test_in_process_fallback():
    rt = ProcessAgentRuntime(use_processes=False)
    res = rt.run(tasks.square, 5)
    assert res.ok and res.value == 25 and res.mode == "in_process"


def test_in_process_failure():
    rt = ProcessAgentRuntime(use_processes=False)
    res = rt.run(tasks.boom, "x")
    assert not res.ok and "x" in res.error


def test_health_and_singleton():
    rt = ProcessAgentRuntime(use_processes=False)
    assert rt.health()["status"] == "ok"
    assert get_agent_runtime() is get_agent_runtime()
