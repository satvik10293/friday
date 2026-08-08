"""
tests/test_harness_upgrades.py — robustness upgrades

Generation-param passthrough, HTTP-status retryable classification, the
reliability layer honoring `retryable`, the orchestrator's token headroom for
thinking models, and the new registry/task helpers. Network-free.
"""

from __future__ import annotations

import asyncio

from core.harness import (BaseProvider, Capability, GenRequest, GenResult,
                          HarnessOrchestrator, ProviderRegistry, RetryPolicy,
                          Task, TaskState, anthropic, make_info, openai,
                          reliable_call)


def run(coro):
    return asyncio.run(coro)


class _HTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"{status} error")
        self.response = type("R", (), {"status_code": status})()


def _raises(status):
    def transport(*_a):
        raise _HTTPError(status)
    return transport


# ── retryable classification ─────────────────────────────────────────────────
def test_http_429_is_retryable():
    res = run(openai(api_key="k", transport=_raises(429)).generate(GenRequest(prompt="x")))
    assert res.ok is False and res.retryable is True and res.meta.get("status") == 429


def test_http_401_is_not_retryable():
    res = run(openai(api_key="k", transport=_raises(401)).generate(GenRequest(prompt="x")))
    assert res.ok is False and res.retryable is False


def test_http_503_is_retryable():
    res = run(openai(api_key="k", transport=_raises(503)).generate(GenRequest(prompt="x")))
    assert res.retryable is True


def test_reliable_call_stops_on_non_retryable():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return GenResult(provider="p", ok=False, retryable=False, error="401")

    res = run(reliable_call(fn, retry=RetryPolicy(max_attempts=5, base_delay_s=0)))
    assert calls["n"] == 1                          # stopped after the first attempt
    assert res.ok is False and res.retryable is False


def test_reliable_call_still_retries_retryable():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        return GenResult(provider="p", ok=calls["n"] >= 2, retryable=True)

    res = run(reliable_call(fn, retry=RetryPolicy(max_attempts=3, base_delay_s=0)))
    assert res.ok and calls["n"] == 2


# ── generation-param passthrough + usage ─────────────────────────────────────
def test_openai_params_and_usage():
    seen = {}

    def transport(url, headers, payload, timeout):
        seen.update(top_p=payload.get("top_p"), stop=payload.get("stop"))
        return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"completion_tokens": 1, "prompt_tokens": 2}}

    res = run(openai(api_key="k", transport=transport).generate(
        GenRequest(prompt="x", top_p=0.5, stop=["END"])))
    assert seen["top_p"] == 0.5 and seen["stop"] == ["END"]
    assert res.tokens == 1 and res.prompt_tokens == 2 and res.total_tokens == 3
    assert res.finish_reason == "stop"


def test_anthropic_params_and_usage():
    seen = {}

    def transport(url, headers, payload, timeout):
        seen.update(top_p=payload.get("top_p"), stop=payload.get("stop_sequences"))
        return {"content": [{"type": "text", "text": "ok"}],
                "usage": {"output_tokens": 1, "input_tokens": 3},
                "stop_reason": "end_turn"}

    res = run(anthropic(api_key="k", transport=transport).generate(
        GenRequest(prompt="x", top_p=0.5, stop=["END"])))
    assert seen["top_p"] == 0.5 and seen["stop"] == ["END"]
    assert res.prompt_tokens == 3 and res.finish_reason == "end_turn"


# ── orchestrator token headroom ──────────────────────────────────────────────
def test_orchestrator_applies_default_max_tokens():
    seen = {}

    class _P(BaseProvider):
        def __init__(self):
            super().__init__(make_info("p", (Capability.TEXT,)))

        async def _generate(self, request):
            seen["max_tokens"] = request.max_tokens
            return GenResult(provider="p", ok=True, text="ok")

    reg = ProviderRegistry()
    reg.register(_P())
    orch = HarnessOrchestrator(reg, default_max_tokens=999,
                               retry=RetryPolicy(max_attempts=1, base_delay_s=0),
                               timeout_s=None)
    run(orch.run("hi"))
    assert seen["max_tokens"] == 999


# ── registry + task helpers ──────────────────────────────────────────────────
class _Ok(BaseProvider):
    def __init__(self, name, kind="cloud"):
        super().__init__(make_info(name, (Capability.TEXT,), kind=kind))

    async def _generate(self, request):
        return GenResult(provider=self.info.name, ok=True, text="ok")


def test_registry_by_kind_and_reset():
    reg = ProviderRegistry()
    reg.register(_Ok("local", kind="local"))
    reg.register(_Ok("cloud", kind="cloud"))
    assert [p.info.name for p in reg.by_kind("local")] == ["local"]
    assert [p.info.name for p in reg.by_kind("cloud")] == ["cloud"]

    br = reg.breaker_for("cloud")
    br.fail_threshold = 1
    br.record_failure()
    assert br.state == "open"
    assert reg.reset("cloud") is True and br.state == "closed"
    assert reg.reset("nope") is False


def test_task_duration_and_tags():
    t = Task(objective="x", tags={"purpose": "test"})
    t.transition(TaskState.RUNNING)
    assert t.duration_ms >= 0.0
    d = t.to_dict()
    assert d["tags"] == {"purpose": "test"} and "duration_ms" in d
