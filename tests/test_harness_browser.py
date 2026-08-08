"""
tests/test_harness_browser.py — FRIDAY harness (browser-seat adapter)

For plan-but-no-key users: FRIDAY drives a logged-in chat seat as just another
provider. The real page automation is behind the injectable `ChatDriver`, so
these tests use a fake driver and never open a browser — proving the provider
contract, the never-raise guarantee, and that a browser seat drops into the same
council/registry as any API model.
"""

from __future__ import annotations

import asyncio

from core.harness import (BrowserProvider, GenRequest, HarnessOrchestrator,
                          ProviderRegistry, RetryPolicy, TaskState, browser_provider,
                          build_registry)


def run(coro):
    return asyncio.run(coro)


class _FakeDriver:
    def __init__(self, *, ready=True, reply="seat reply", raises=False):
        self._ready, self._reply, self._raises = ready, reply, raises
        self.seen = None
        self.closed = False

    def is_ready(self):
        return self._ready

    def ask(self, message, *, timeout_s):
        self.seen = message
        if self._raises:
            raise RuntimeError("page blew up")
        return self._reply

    def close(self):
        self.closed = True


def test_browser_provider_returns_seat_reply():
    d = _FakeDriver(reply="ChatGPT (web) says hi")
    p = browser_provider("chatgpt", driver=d)
    assert p.available() is True
    res = run(p.generate(GenRequest(prompt="hello", system="be brief")))
    assert res.ok and res.text == "ChatGPT (web) says hi"
    assert res.meta["kind"] == "browser" and p.info.name == "chatgpt-web"
    # system + prompt were folded into the single chat message
    assert "be brief" in d.seen and "hello" in d.seen


def test_browser_provider_unavailable_when_not_logged_in():
    p = browser_provider("claude", driver=_FakeDriver(ready=False))
    assert p.available() is False
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False and "not logged in" in res.error


def test_browser_provider_never_raises_on_driver_error():
    p = browser_provider("gemini", driver=_FakeDriver(raises=True))
    res = run(p.generate(GenRequest(prompt="x")))
    assert res.ok is False and "page blew up" in res.error


def test_browser_provider_uses_lazy_factory():
    built = {"n": 0}

    def factory():
        built["n"] += 1
        return _FakeDriver(reply="lazy reply")

    p = BrowserProvider(name="claude-web", driver_factory=factory)
    assert p.available() is True                     # factory present → optimistic
    res = run(p.generate(GenRequest(prompt="hi")))
    assert res.ok and res.text == "lazy reply" and built["n"] == 1


def test_browser_seat_joins_the_council(monkeypatch):
    # a plan-only user: no cloud API keys, but a driven ChatGPT + Claude seat
    for env in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                "XAI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    reg = build_registry(include_local=False, only_available=True,
                         browser_drivers={"chatgpt": _FakeDriver(reply="A"),
                                          "claude": _FakeDriver(reply="B")})
    names = {p.info.name for p in reg.all()}
    assert names == {"chatgpt-web", "claude-web"}

    orch = HarnessOrchestrator(reg, retry=RetryPolicy(max_attempts=1, base_delay_s=0),
                               timeout_s=None)
    task = run(orch.council("compare A and B", synthesize=False))
    assert task.state is TaskState.COMPLETED
    assert set(task.result.meta["council"]) == {"chatgpt-web", "claude-web"}
