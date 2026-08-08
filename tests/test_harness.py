"""
tests/test_harness.py — FRIDAY harness Phase 1 (reliable core)

Covers the provider abstraction, reliability primitives, provider registry,
task lifecycle FSM, and the Groq/Local adapters. Async paths are driven through
`asyncio.run` so the suite needs no pytest-asyncio plugin.
"""

from __future__ import annotations

import asyncio

import pytest

from core.harness import (BaseProvider, Capability, CircuitBreaker,
                          CircuitOpenError, GenRequest, GenResult,
                          IllegalTransition, ProviderRegistry, RetryPolicy,
                          Task, TaskState, make_info, reliable_call)
from core.harness.groq_provider import GroqProvider
from core.harness.local_provider import LocalProvider


def run(coro):
    return asyncio.run(coro)


# ── test doubles ─────────────────────────────────────────────────────────────
class _OkProvider(BaseProvider):
    def __init__(self, name="ok", cost=0.0, caps=(Capability.TEXT,)):
        super().__init__(make_info(name, caps, cost_hint=cost))

    async def _generate(self, request):
        return GenResult(provider=self.info.name, ok=True, text="hi")


class _RaisingProvider(BaseProvider):
    def __init__(self):
        super().__init__(make_info("boom", (Capability.TEXT,)))

    async def _generate(self, request):
        raise RuntimeError("kaboom")


# ── providers ────────────────────────────────────────────────────────────────
def test_base_provider_never_raises_and_times():
    p = _RaisingProvider()
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False
    assert "kaboom" in res.error
    assert res.provider == "boom"          # filled in by the base wrapper
    assert res.latency_ms >= 0.0


def test_base_provider_fills_provider_and_latency():
    res = run(_OkProvider().generate(GenRequest(prompt="x")))
    assert res.ok and res.text == "hi" and res.provider == "ok"


def test_info_supports_accepts_enum_or_str():
    info = make_info("m", (Capability.CODE,))
    assert info.supports(Capability.CODE) and info.supports("code")
    assert not info.supports("vision")


# ── reliability ──────────────────────────────────────────────────────────────
def test_retry_policy_backoff():
    rp = RetryPolicy(base_delay_s=0.1, backoff=2.0, max_delay_s=1.0)
    assert rp.delay(1) == pytest.approx(0.1)
    assert rp.delay(2) == pytest.approx(0.2)
    assert rp.delay(10) == pytest.approx(1.0)   # capped


def test_circuit_breaker_opens_and_half_opens():
    cb = CircuitBreaker(fail_threshold=2, reset_timeout_s=0.0)
    assert cb.allow() and cb.state == "closed"
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    # reset_timeout 0 → next allow() probes (half-open)
    assert cb.allow() is True and cb.state == "half_open"
    cb.record_success()
    assert cb.state == "closed"


def test_circuit_breaker_reopens_on_halfopen_failure():
    cb = CircuitBreaker(fail_threshold=1, reset_timeout_s=0.0)
    cb.record_failure()
    assert cb.state == "open"
    assert cb.allow() and cb.state == "half_open"
    cb.record_failure()                          # probe failed
    assert cb.state == "open"


def test_reliable_call_retries_then_succeeds():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return GenResult(provider="p", ok=calls["n"] >= 2)

    res = run(reliable_call(fn, retry=RetryPolicy(max_attempts=3, base_delay_s=0)))
    assert res.ok and calls["n"] == 2


def test_reliable_call_returns_last_failure_when_exhausted():
    async def fn():
        return GenResult(provider="p", ok=False, error="nope")

    res = run(reliable_call(fn, retry=RetryPolicy(max_attempts=2, base_delay_s=0)))
    assert res is not None and res.ok is False and res.error == "nope"


def test_reliable_call_timeout_counts_as_failure():
    async def slow():
        await asyncio.sleep(0.2)
        return GenResult(provider="p", ok=True)

    res = run(reliable_call(slow, retry=RetryPolicy(max_attempts=1, base_delay_s=0),
                            timeout_s=0.01))
    assert res is None                            # timed out, no result to return


def test_reliable_call_circuit_open_raises_when_no_prior_result():
    cb = CircuitBreaker(fail_threshold=1, reset_timeout_s=60.0)
    cb.record_failure()                           # now OPEN, cooldown long

    async def fn():
        return GenResult(provider="p", ok=True)

    with pytest.raises(CircuitOpenError):
        run(reliable_call(fn, retry=RetryPolicy(max_attempts=1), breaker=cb))


# ── registry ─────────────────────────────────────────────────────────────────
def test_registry_prefers_cheaper_capable_provider():
    reg = ProviderRegistry()
    reg.register(_OkProvider(name="cloud", cost=1.0))
    reg.register(_OkProvider(name="local", cost=0.0))
    order = [p.info.name for p in reg.by_capability(Capability.TEXT)]
    assert order[0] == "local"                    # free beats paid


def test_registry_deprioritizes_open_breaker():
    reg = ProviderRegistry()
    reg.register(_OkProvider(name="a", cost=0.0))
    reg.register(_OkProvider(name="b", cost=0.5))
    reg.breaker_for("a").fail_threshold = 1
    reg.breaker_for("a").reset_timeout_s = 60.0
    reg.breaker_for("a").record_failure()         # a is now unusable
    order = [p.info.name for p in reg.by_capability(Capability.TEXT)]
    assert order[0] == "b" and order[-1] == "a"


def test_registry_capability_filtering():
    reg = ProviderRegistry()
    reg.register(_OkProvider(name="texter", caps=(Capability.TEXT,)))
    reg.register(_OkProvider(name="coder", caps=(Capability.CODE,)))
    assert [p.info.name for p in reg.by_capability(Capability.CODE)] == ["coder"]
    assert reg.best_for(Capability.VISION) is None


# ── task FSM ─────────────────────────────────────────────────────────────────
def test_task_happy_path():
    t = Task(objective="do the thing")
    assert t.state is TaskState.CREATED
    t.transition(TaskState.PLANNING)
    t.transition(TaskState.DELEGATING)
    t.transition(TaskState.RUNNING)
    t.transition(TaskState.VERIFYING)
    t.complete(result="done")
    assert t.succeeded and t.is_terminal and t.result == "done"
    assert [e.to for e in t.history][-1] == "completed"


def test_task_illegal_transition_raises():
    t = Task(objective="x")
    with pytest.raises(IllegalTransition):
        t.transition(TaskState.COMPLETED)         # CREATED → COMPLETED not allowed


def test_task_terminal_is_frozen():
    t = Task(objective="x")
    t.fail("bad")
    assert t.state is TaskState.FAILED and t.is_terminal
    with pytest.raises(IllegalTransition):
        t.transition(TaskState.RUNNING)


def test_task_retry_and_escalate_paths():
    t = Task(objective="x")
    t.transition(TaskState.RUNNING)
    t.transition(TaskState.RETRYING)
    t.transition(TaskState.RUNNING)               # retry loop is legal
    t.transition(TaskState.ESCALATED)
    t.transition(TaskState.COMPLETED)             # human/other agent resolved it
    assert t.succeeded


# ── adapters ─────────────────────────────────────────────────────────────────
def test_groq_provider_uses_injected_transport():
    seen = {}

    def fake_transport(url, headers, payload, timeout):
        seen["url"] = url
        seen["model"] = payload["model"]
        return {"choices": [{"message": {"content": "cloud says hi"}}],
                "usage": {"completion_tokens": 3}}

    p = GroqProvider(model="test-model", api_key="k", transport=fake_transport)
    assert p.available()
    res = run(p.generate(GenRequest(prompt="hello", system="be nice")))
    assert res.ok and res.text == "cloud says hi" and res.tokens == 3
    assert seen["model"] == "test-model" and "groq.com" in seen["url"]


def test_groq_provider_without_key_is_unavailable():
    p = GroqProvider(api_key="")
    assert p.available() is False
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False and "GROQ_API_KEY" in res.error


def test_local_provider_maps_intelligence_os_response():
    class _FakeResp:
        ok, answer, confidence, latency_ms = True, "local answer", 0.8, 12.0
        error, trace_id, models_used = "", "tr1", ["mini"]

    class _FakeIOS:
        def think(self, prompt, task=None, context=None):
            assert prompt == "q"
            return _FakeResp()

    p = LocalProvider(ios=_FakeIOS())
    res = run(p.generate(GenRequest(prompt="q")))
    assert res.ok and res.text == "local answer"
    assert res.confidence == 0.8 and res.meta["trace_id"] == "tr1"
