"""
tests/test_harness_council.py — FRIDAY harness (council + hybrid routing)

The "make the best thing" behaviour: ask several providers in parallel and
synthesize one best answer, and the hybrid router that sends simple asks to a
single model and hard asks to the council. Network-free via provider doubles.
"""

from __future__ import annotations

import asyncio

from core.harness import (BaseProvider, Capability, GenRequest, GenResult,
                          HarnessOrchestrator, ProviderRegistry, RetryPolicy,
                          TaskState, is_hard, make_info)


def run(coro):
    return asyncio.run(coro)


class _P(BaseProvider):
    def __init__(self, name, text, *, ok=True, cost=0.0, kind="local",
                 caps=(Capability.TEXT,)):
        super().__init__(make_info(name, caps, cost_hint=cost, kind=kind))
        self._text, self._ok = text, ok
        self.calls = 0

    async def _generate(self, request):
        self.calls += 1
        if self._ok:
            return GenResult(provider=self.info.name, ok=True, text=self._text)
        return GenResult(provider=self.info.name, ok=False, error="fail")


class _Synth(BaseProvider):
    """Synthesizer double that records the prompt it was handed."""

    def __init__(self, name="synth", cost=5.0, kind="local"):
        super().__init__(make_info(name, (Capability.TEXT,), cost_hint=cost, kind=kind))
        self.seen_prompt = None

    async def _generate(self, request):
        self.seen_prompt = request.prompt
        return GenResult(provider=self.info.name, ok=True, text="SYNTH")


def _orch(providers, **kw):
    reg = ProviderRegistry()
    for p in providers:
        reg.register(p)
    kw.setdefault("retry", RetryPolicy(max_attempts=1, base_delay_s=0))
    kw.setdefault("timeout_s", None)
    return HarnessOrchestrator(reg, **kw), reg


# ── council ──────────────────────────────────────────────────────────────────
def test_council_synthesizes_candidates():
    a, b, synth = _P("a", "answer-A"), _P("b", "answer-B"), _Synth()
    orch, _ = _orch([a, b, synth])
    task = run(orch.council("q", providers=[a, b], synthesizer=synth))
    assert task.state is TaskState.COMPLETED
    assert task.result.text == "SYNTH"
    assert task.result.meta["synthesized"] is True
    assert set(task.result.meta["council"]) == {"a", "b"}
    assert "answer-A" in synth.seen_prompt and "answer-B" in synth.seen_prompt
    assert a.calls == 1 and b.calls == 1               # ran in parallel, once each


def test_council_single_usable_answer_skips_synthesis():
    a, bad = _P("a", "only-A"), _P("bad", "", ok=False)
    orch, _ = _orch([a, bad])
    task = run(orch.council("q", providers=[a, bad]))
    assert task.state is TaskState.COMPLETED and task.result.text == "only-A"
    assert task.result.meta["council"] == ["a"]


def test_council_all_fail():
    orch, _ = _orch([_P("a", "", ok=False), _P("b", "", ok=False)])
    task = run(orch.council("q"))
    assert task.state is TaskState.FAILED


def test_council_synthesis_failure_falls_back_to_candidate():
    a, b = _P("a", "cand-A"), _P("b", "cand-B")
    bad_synth = _P("bad", "", ok=False)
    orch, _ = _orch([a, b, bad_synth])
    task = run(orch.council("q", providers=[a, b], synthesizer=bad_synth))
    assert task.state is TaskState.COMPLETED
    assert task.result.text in ("cand-A", "cand-B")
    assert task.result.meta["synthesized"] is False
    assert "synth_error" in task.result.meta


def test_council_respects_size_limit():
    ps = [_P(f"p{i}", f"a{i}") for i in range(5)]
    orch, _ = _orch(ps, council_size=2)
    run(orch.council("q", synthesize=False))           # isolate the member count
    assert sum(p.calls for p in ps) == 2               # only 2 of 5 consulted
    assert ps[2].calls == 0 and ps[3].calls == 0 and ps[4].calls == 0


def test_council_includes_all_available_by_default():
    # the whole council convenes — no paid provider is dropped by a size cap
    ps = [_P(f"p{i}", f"a{i}", kind="cloud", cost=i * 0.3) for i in range(4)]
    orch, _ = _orch(ps)                                 # council_size default = None
    run(orch.council("q", synthesize=False))
    assert all(p.calls == 1 for p in ps)               # every subscription voted


def test_default_synthesizer_prefers_strongest_cloud():
    # a strong cloud model reconciles — never the weak local one
    local = _P("local", "L", kind="local", cost=0.0)
    cheap_cloud = _P("groqish", "G", kind="cloud", cost=0.3)
    strong_cloud = _Synth("claudeish", cost=1.1, kind="cloud")
    orch, _ = _orch([local, cheap_cloud, strong_cloud])
    task = run(orch.council("q"))                       # no explicit synthesizer
    assert task.state is TaskState.COMPLETED
    assert task.provider == "claudeish"                # strongest cloud synthesized
    assert task.result.meta["synthesized"] is True


# ── hybrid routing ───────────────────────────────────────────────────────────
def test_is_hard_heuristic():
    assert is_hard("write a function to sort a list", Capability.CODE) is True
    assert is_hard("explain why the sky is blue") is True
    assert is_hard("what time is it") is False
    assert is_hard("hi") is False


def test_run_auto_simple_uses_single_model():
    a = _P("a", "single-answer")
    orch, _ = _orch([a])
    task = run(orch.run_auto("what time is it"))
    assert task.state is TaskState.COMPLETED and task.result.text == "single-answer"
    assert "council" not in (task.result.meta or {})


def test_run_auto_hard_convenes_council():
    a, b, synth = _P("a", "A"), _P("b", "B"), _Synth()
    orch, _ = _orch([a, b, synth], synthesizer="synth")
    task = run(orch.run_auto("explain why recursion works step by step"))
    assert task.state is TaskState.COMPLETED
    assert task.result.meta.get("synthesized") is True


def test_run_auto_hard_override():
    a, b, synth = _P("a", "A"), _P("b", "B"), _Synth()
    orch, _ = _orch([a, b, synth], synthesizer="synth")
    task = run(orch.run_auto("hi", hard=True))
    assert task.result.meta.get("synthesized") is True


def test_run_auto_sync_bridge():
    orch, _ = _orch([_P("a", "sync-answer")])
    task = orch.run_auto_sync("what time is it")
    assert task.state is TaskState.COMPLETED and task.result.text == "sync-answer"
