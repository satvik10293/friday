"""
tests/test_harness_orchestrator.py — FRIDAY harness (orchestration)

Exercises the end-to-end orchestration paths without a network: provider
fallback, verification reject → fallback, escalation, honest failure, and the
task lifecycle each path walks. Async is driven through `asyncio.run`.
"""

from __future__ import annotations

import asyncio

import pytest

from core.harness import (BaseProvider, Capability, GenRequest, GenResult,
                          HarnessOrchestrator, ProviderRegistry, RetryPolicy,
                          TaskState, Verdict, make_info)


def run(coro):
    return asyncio.run(coro)


class _Provider(BaseProvider):
    """Configurable double: succeeds with `text`, or fails, on demand."""

    def __init__(self, name, *, ok=True, text="", error="fail", cost=0.0):
        super().__init__(make_info(name, (Capability.TEXT,), cost_hint=cost))
        self._ok, self._text, self._error = ok, text or name, error
        self.calls = 0

    async def _generate(self, request):
        self.calls += 1
        if self._ok:
            return GenResult(provider=self.info.name, ok=True, text=self._text)
        return GenResult(provider=self.info.name, ok=False, error=self._error)


def _orch(*providers, **kw):
    reg = ProviderRegistry()
    for p in providers:
        reg.register(p)
    kw.setdefault("retry", RetryPolicy(max_attempts=1, base_delay_s=0))
    kw.setdefault("timeout_s", None)
    return HarnessOrchestrator(reg, **kw), reg


# ── happy path ───────────────────────────────────────────────────────────────
def test_single_provider_completes():
    orch, _ = _orch(_Provider("local", text="answer"))
    task = run(orch.run("what is 2+2"))
    assert task.state is TaskState.COMPLETED
    assert task.result.text == "answer" and task.provider == "local"


def test_no_provider_fails_honestly():
    orch, _ = _orch()                              # empty registry
    task = run(orch.run("x", capability=Capability.VISION))
    assert task.state is TaskState.FAILED and "no provider" in task.error


# ── fallback ─────────────────────────────────────────────────────────────────
def test_falls_back_to_next_provider_on_failure():
    bad = _Provider("cloud", ok=False, cost=1.0)
    good = _Provider("local", ok=True, text="local wins", cost=0.0)
    orch, _ = _orch(bad, good)
    task = run(orch.run("q"))
    # local is cheaper so it is tried first and wins outright
    assert task.state is TaskState.COMPLETED and task.result.text == "local wins"
    assert good.calls == 1


def test_falls_back_when_preferred_provider_fails():
    # preferred (cheaper) provider fails → harness must try the pricier backup
    preferred = _Provider("local", ok=False, cost=0.0)
    backup = _Provider("cloud", ok=True, text="cloud saved it", cost=1.0)
    orch, _ = _orch(preferred, backup)
    task = run(orch.run("q"))
    assert task.state is TaskState.COMPLETED and task.result.text == "cloud saved it"
    assert preferred.calls == 1 and backup.calls == 1
    # the task passed through RETRYING on its way to the backup
    assert any(e.to == "retrying" for e in task.history)


def test_all_providers_fail_without_escalation():
    orch, _ = _orch(_Provider("a", ok=False, cost=0.0),
                    _Provider("b", ok=False, cost=1.0, error="b-broke"))
    task = run(orch.run("q"))
    assert task.state is TaskState.FAILED and task.error == "b-broke"


# ── verification ─────────────────────────────────────────────────────────────
def test_verifier_rejects_then_falls_back():
    weak = _Provider("weak", ok=True, text="wrong", cost=0.0)
    strong = _Provider("strong", ok=True, text="correct", cost=1.0)

    def verify(task, result):
        return Verdict(accepted=result.text == "correct", reason="must be correct")

    orch, _ = _orch(weak, strong, verifier=verify)
    task = run(orch.run("q"))
    assert task.state is TaskState.COMPLETED and task.result.text == "correct"
    assert any(e.to == "verifying" for e in task.history)


def test_verifier_rejects_all_fails():
    p = _Provider("only", ok=True, text="nope", cost=0.0)
    orch, _ = _orch(p, verifier=lambda t, r: Verdict(accepted=False, retry=True))
    task = run(orch.run("q"))
    assert task.state is TaskState.FAILED


def test_bool_returning_verifier_supported():
    orch, _ = _orch(_Provider("p", text="ok"), verifier=lambda t, r: True)
    task = run(orch.run("q"))
    assert task.state is TaskState.COMPLETED


# ── escalation ───────────────────────────────────────────────────────────────
def test_escalation_resolves_after_all_fail():
    async def human(task, last):
        return GenResult(provider="human", ok=True, text="escalated answer")

    orch, _ = _orch(_Provider("a", ok=False), escalate=human)
    task = run(orch.run("q"))
    assert task.state is TaskState.COMPLETED
    assert task.result.text == "escalated answer"
    assert any(e.to == "escalated" for e in task.history)


def test_escalation_that_declines_still_fails():
    orch, _ = _orch(_Provider("a", ok=False, error="down"),
                    escalate=lambda t, l: None)
    task = run(orch.run("q"))
    assert task.state is TaskState.FAILED


# ── observability ────────────────────────────────────────────────────────────
def test_events_are_emitted():
    events = []
    orch, _ = _orch(_Provider("p", text="hi"),
                    on_event=lambda e, d: events.append(e))
    run(orch.run("q"))
    names = set(events)
    assert "task_started" in names and "completed" in names


def test_sync_bridge_runs():
    orch, _ = _orch(_Provider("p", text="sync-ok"))
    task = orch.run_sync("q")
    assert task.state is TaskState.COMPLETED and task.result.text == "sync-ok"
