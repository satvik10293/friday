"""
core/harness/orchestrator.py — FRIDAY harness (orchestration)

Where the primitives become a harness. Given an objective and a capability, the
orchestrator drives a `Task` through its lifecycle: select the best provider,
execute it with timeout + retry + circuit breaker, optionally VERIFY the result,
and on failure fall back to the next capable provider, retry, escalate, or fail
honestly — every transition logged.

This is the embodiment of FRIDAY's core principle: it coordinates providers far
more capable than itself and decides when/why/how to use them, without doing the
hard reasoning itself. It does NOT plan multi-step workflows yet (that is the
next increment, layering the executive planner on top) — it reliably runs one
capability request end to end, which is the unit every larger workflow is built
from.

Reliability contract:
    · providers never raise (BaseProvider guarantees it); a bad result or a
      timeout is a failed attempt the harness routes around
    · fallback walks the registry's capability chain (healthiest/cheapest first)
    · a verifier can REJECT a result and send the task back for another provider
    · when nothing works: escalate (if a handler is wired) else FAIL honestly —
      never a silent success
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Protocol, Union

from .providers import (Capability, GenRequest, GenResult, ModelProvider,
                        as_capability)
from .registry import ProviderRegistry
from .reliability import RetryPolicy, reliable_call
from .task import Task, TaskState

log = logging.getLogger("friday.harness.orchestrator")


@dataclass
class Verdict:
    """A verifier's judgement of a result."""
    accepted: bool
    reason: str = ""
    retry: bool = True          # if rejected: try another provider (True) or stop


class Verifier(Protocol):
    async def verify(self, task: Task, result: GenResult) -> Verdict:
        ...


# A verifier may be a Verifier object, or a plain (sync/async) callable
# (task, result) -> Verdict | bool.
VerifierLike = Union[Verifier, Callable[[Task, GenResult], object]]
# An escalation handler: (task, last_result) -> GenResult | None  (sync or async).
EscalateLike = Callable[[Task, Optional[GenResult]], object]
EventSink = Callable[[str, dict], None]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _run_verifier(v: VerifierLike, task: Task, result: GenResult) -> Verdict:
    raw = v.verify(task, result) if hasattr(v, "verify") else v(task, result)
    verdict = await _maybe_await(raw)
    if isinstance(verdict, Verdict):
        return verdict
    return Verdict(accepted=bool(verdict))          # bool-returning verifiers


class HarnessOrchestrator:
    def __init__(self, registry: ProviderRegistry, *,
                 retry: Optional[RetryPolicy] = None,
                 timeout_s: Optional[float] = 30.0,
                 max_providers: int = 3,
                 council_size: Optional[int] = None,
                 synthesizer: Optional[Union[str, ModelProvider]] = None,
                 verifier: Optional[VerifierLike] = None,
                 escalate: Optional[EscalateLike] = None,
                 on_event: Optional[EventSink] = None) -> None:
        self._registry = registry
        self._retry = retry or RetryPolicy(max_attempts=2, base_delay_s=0.2)
        self._timeout_s = timeout_s
        self._max_providers = max_providers
        self._council_size = council_size
        self._synthesizer = synthesizer
        self._verifier = verifier
        self._escalate = escalate
        self._on_event = on_event

    # ── public ───────────────────────────────────────────────────────────────────
    async def run(self, objective: str, *, capability=Capability.TEXT,
                  context: Optional[dict] = None, system: str = "",
                  request: Optional[GenRequest] = None,
                  verifier: Optional[VerifierLike] = None) -> Task:
        cap = as_capability(capability)
        task = Task(objective=objective, capability=cap, context=dict(context or {}))
        verifier = verifier if verifier is not None else self._verifier
        req = request or GenRequest(prompt=objective, task=cap,
                                    context=task.context, system=system)

        providers = self._registry.by_capability(cap)[: self._max_providers]
        self._emit("task_started", task, capability=cap,
                   providers=[p.info.name for p in providers])
        if not providers:
            task.fail(f"no provider registered for capability {cap!r}")
            self._emit("failed", task, reason=task.error)
            return task

        last: Optional[GenResult] = None
        for i, provider in enumerate(providers):
            task.provider = provider.info.name
            task.attempts += 1
            self._to_running(task)
            self._emit("provider_selected", task, provider=provider.info.name,
                       attempt=task.attempts)

            result = await reliable_call(
                lambda p=provider: p.generate(req),
                retry=self._retry, breaker=self._registry.breaker_for(provider.info.name),
                timeout_s=self._timeout_s,
                on_event=self._provider_event_sink(provider.info.name, task))

            if result is None or not result.ok:
                last = result if result is not None else last
                self._emit("attempt_failed", task, provider=provider.info.name,
                           error=(result.error if result else "timeout/exhausted"))
                if i < len(providers) - 1:
                    task.transition(TaskState.RETRYING, note="provider failed")
                continue

            # a usable result — verify it if a verifier is wired
            if verifier is not None:
                task.transition(TaskState.VERIFYING)
                verdict = await _run_verifier(verifier, task, result)
                self._emit("verify_verdict", task, accepted=verdict.accepted,
                           reason=verdict.reason)
                if not verdict.accepted:
                    last = result
                    if verdict.retry and i < len(providers) - 1:
                        task.transition(TaskState.RETRYING, note=verdict.reason)
                        continue
                    break                          # rejected, no more retries
            task.complete(result=result, note=f"via {provider.info.name}")
            self._emit("completed", task, provider=provider.info.name)
            return task

        # nothing accepted → escalate or fail honestly
        return await self._escalate_or_fail(task, last)

    def run_sync(self, objective: str, **kw) -> Task:
        """Sync bridge for the sync voice loop (mirrors IntelligenceOS.think)."""
        return asyncio.run(self.run(objective, **kw))

    # ── council: ask several, synthesize the best ────────────────────────────────
    async def council(self, objective: str, *, capability=Capability.TEXT,
                      context: Optional[dict] = None, system: str = "",
                      request: Optional[GenRequest] = None,
                      providers: Optional[list] = None, synthesize: bool = True,
                      synthesizer: Optional[Union[str, ModelProvider]] = None,
                      min_success: int = 1) -> Task:
        """Query several capable providers in PARALLEL, then synthesize their
        answers into one. This is how FRIDAY turns the user's separate AI
        subscriptions into a single, cross-checked best answer for hard asks."""
        cap = as_capability(capability)
        task = Task(objective=objective, capability=cap, context=dict(context or {}))
        req = request or GenRequest(prompt=objective, task=cap,
                                    context=task.context, system=system)
        chosen = (providers if providers is not None
                  else self._registry.by_capability(cap))
        chosen = [p for p in chosen if p.available()]
        # By default the whole council convenes — every subscription the user has
        # is a voice — so a paid frontier model is never silently dropped. A cap
        # is opt-in (cost control) via `council_size`.
        if self._council_size is not None:
            chosen = chosen[: self._council_size]
        self._emit("council_started", task, providers=[p.info.name for p in chosen])
        if not chosen:
            task.fail(f"no available provider for capability {cap!r}")
            self._emit("failed", task, reason=task.error)
            return task
        self._to_running(task)

        async def call(p: ModelProvider):
            res = await reliable_call(
                lambda p=p: p.generate(req), retry=self._retry,
                breaker=self._registry.breaker_for(p.info.name),
                timeout_s=self._timeout_s,
                on_event=self._provider_event_sink(p.info.name, task))
            return p.info.name, res

        pairs = await asyncio.gather(*[call(p) for p in chosen])
        task.attempts += len(chosen)
        good = [(n, r) for n, r in pairs if r is not None and r.ok]
        self._emit("council_gathered", task, asked=len(chosen), answered=len(good))
        if len(good) < min_success:
            last = next((r for _, r in pairs if r is not None), None)
            return await self._escalate_or_fail(task, last)

        if len(good) == 1 or not synthesize:
            best = max((r for _, r in good), key=lambda r: r.confidence)
            best.meta = {**best.meta, "council": [n for n, _ in good]}
            task.provider = best.provider
            task.complete(result=best, note="council (single usable answer)")
            self._emit("completed", task, provider=best.provider, mode="council")
            return task

        task.transition(TaskState.VERIFYING)
        synth = await self._synthesize(objective, good, cap, task,
                                       synthesizer or self._synthesizer)
        task.provider = synth.provider
        task.complete(result=synth, note="council (synthesized)")
        self._emit("completed", task, provider=synth.provider, mode="council")
        return task

    # ── hybrid: route simple, council hard ───────────────────────────────────────
    async def run_auto(self, objective: str, *, capability=Capability.TEXT,
                       context: Optional[dict] = None, system: str = "",
                       request: Optional[GenRequest] = None,
                       hard: Optional[bool] = None) -> Task:
        """The default entry point: easy asks go to the single best model (fast,
        cheap); hard asks convene the council. `hard` overrides the heuristic."""
        if hard is None:
            hard = is_hard(objective, capability)
        self._emit_plain("route_decision", objective=objective[:80], hard=hard)
        if hard:
            return await self.council(objective, capability=capability,
                                      context=context, system=system, request=request)
        return await self.run(objective, capability=capability, context=context,
                              system=system, request=request)

    def run_auto_sync(self, objective: str, **kw) -> Task:
        return asyncio.run(self.run_auto(objective, **kw))

    def has_available_provider(self, capability=Capability.TEXT) -> bool:
        """Whether any registered provider for `capability` is usable right now.
        Callers (e.g. the conversation bridge) use this to skip the harness
        entirely when the user has configured no reachable models."""
        return any(p.available() for p in self._registry.by_capability(capability))

    # ── internals ────────────────────────────────────────────────────────────────
    async def _synthesize(self, objective: str, good: list, cap: str, task: Task,
                          synthesizer) -> GenResult:
        provider = self._resolve_synthesizer(synthesizer, cap)
        candidates = [(n, r.text) for n, r in good]
        if provider is None:                       # nothing to synthesize with
            return _best_candidate(good, synthesized=False, error="no synthesizer")
        req = GenRequest(prompt=_synthesis_prompt(objective, candidates), task=cap,
                         system=_SYNTH_SYSTEM, max_tokens=1200, temperature=0.2)
        res = await reliable_call(
            lambda: provider.generate(req), retry=self._retry,
            breaker=self._registry.breaker_for(provider.info.name),
            timeout_s=self._timeout_s,
            on_event=self._provider_event_sink(provider.info.name, task))
        if res is None or not res.ok:              # synthesis failed → best candidate
            return _best_candidate(good, synthesized=False,
                                   error=(res.error if res else "timeout"))
        res.meta = {**res.meta, "council": [n for n, _ in good], "synthesized": True,
                    "candidates": {n: t for n, t in candidates}}
        self._emit("synthesized", task, by=provider.info.name,
                   from_providers=[n for n, _ in good])
        return res

    def _resolve_synthesizer(self, synthesizer, cap: str) -> Optional[ModelProvider]:
        if isinstance(synthesizer, ModelProvider):
            return synthesizer
        if isinstance(synthesizer, str):
            p = self._registry.get(synthesizer)
            if p is not None and p.available():
                return p
        usable = [p for p in self._registry.by_capability(cap) if p.available()]
        # A strong CLOUD model reconciles the candidates — synthesis is where
        # quality is decided, so never hand it to the weak local mind while a
        # frontier model is available. `cost_hint` is our strength proxy.
        cloud = [p for p in usable if p.info.kind == "cloud"]
        if cloud:
            return max(cloud, key=lambda p: p.info.cost_hint)
        return usable[0] if usable else None

    def _emit_plain(self, event: str, **data) -> None:
        log.debug("harness %s %s", event, data)
        if self._on_event is not None:
            try:
                self._on_event(event, data)
            except Exception:  # noqa: BLE001
                log.debug("harness event sink failed", exc_info=True)

    def _to_running(self, task: Task) -> None:
        if task.state is not TaskState.RUNNING:
            task.transition(TaskState.RUNNING)

    async def _escalate_or_fail(self, task: Task, last: Optional[GenResult]) -> Task:
        if self._escalate is not None:
            task.transition(TaskState.ESCALATED, note="all providers exhausted")
            self._emit("escalated", task)
            resolved = await _maybe_await(self._escalate(task, last))
            if isinstance(resolved, GenResult) and resolved.ok:
                task.complete(result=resolved, note="resolved via escalation")
                self._emit("completed", task, provider="escalation")
                return task
        reason = (last.error if last and last.error else "all providers failed")
        task.fail(reason)
        self._emit("failed", task, reason=reason)
        return task

    def _provider_event_sink(self, provider_name: str, task: Task) -> EventSink:
        def sink(event: str, data: dict) -> None:
            self._emit(f"reliability.{event}", task, provider=provider_name, **data)
        return sink

    def _emit(self, event: str, task: Task, **data) -> None:
        payload = {"task_id": task.task_id, "state": task.state.value, **data}
        log.debug("harness %s %s", event, payload)
        if self._on_event is not None:
            try:
                self._on_event(event, payload)
            except Exception:  # noqa: BLE001 — observability must never break a run
                log.debug("harness event sink failed", exc_info=True)


# ── difficulty heuristic (hybrid routing) ────────────────────────────────────
_HARD_RE = re.compile(
    r"\b(why|how|prove|derive|solve|explain|compare|design|plan|analyz|"
    r"evaluate|debug|optimi[sz]e|refactor|implement|architect|"
    r"step by step|trade-?offs?|pros and cons)\b", re.I)


def is_hard(objective: str, capability=Capability.TEXT) -> bool:
    """Cheap heuristic: coding/reasoning/planning, long, or reasoning-shaped
    asks convene the council; short factual/chat asks route to one model."""
    if as_capability(capability) in ("code", "reasoning", "planning"):
        return True
    o = objective or ""
    return len(o) >= 160 or bool(_HARD_RE.search(o))


_SYNTH_SYSTEM = (
    "You are FRIDAY's answer synthesizer. You are given several candidate answers "
    "to one question from different AI models. Judge them for correctness, "
    "reconcile any conflicts, discard what is wrong, and produce the single best "
    "answer. Never mention that you compared answers or that other models exist.")


def _synthesis_prompt(objective: str, candidates: list) -> str:
    lines = [f"Question:\n{objective}\n",
             f"Here are {len(candidates)} candidate answers from different AI models:"]
    for i, (name, text) in enumerate(candidates, 1):
        lines.append(f"\n[Answer {i} — {name}]\n{text}")
    lines.append("\nCross-check them, resolve disagreements, and write the single "
                 "best, correct, concise final answer.")
    return "\n".join(lines)


def _best_candidate(good: list, *, synthesized: bool, error: str = "") -> GenResult:
    """Fallback when synthesis is impossible/failed: the highest-confidence
    candidate, tagged so the caller can see it was not synthesized."""
    best = max((r for _, r in good), key=lambda r: r.confidence)
    best.meta = {**best.meta, "council": [n for n, _ in good],
                 "synthesized": synthesized}
    if error:
        best.meta["synth_error"] = error
    return best
