"""
core/skills/executor.py — FRIDAY 4.0
The Skill Executor: the ONE approved execution path for everything FRIDAY does.

Pipeline (per call, every step observable):
  resolve → validate → policy → role-gate → approval → sandboxed run →
  audit + decision-log + security-log + metrics + events → structured Result.

Integrates with: Runtime (events + async skills), Decision Log + Tracing
(observability), Memory Service (via SkillContext). Nothing executes silently;
nothing bypasses this class.

Security imports are lazy (in __init__) to keep core.skills import-time free of
any cycle with core.security.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Optional

from .exceptions import (
    ApprovalRejected,
    PermissionDenied,
    PolicyViolation,
    SandboxTimeout,
    SkillError,
)
from .permissions import RiskLevel, requires_approval
from .results import FailureResult, Result, SuccessResult

log = logging.getLogger("friday.skills.executor")

_SECURITY_EVENT = {
    "PermissionDenied": ("permission_violation", "high"),
    "ApprovalRejected": ("failed_approval", "medium"),
    "ApprovalTimeout": ("failed_approval", "low"),
    "PolicyViolation": ("policy_violation", "high"),
    "SandboxTimeout": ("suspicious", "medium"),
}


def _summarize(result: Result) -> str:
    if result.success:
        d = result.data
        if isinstance(d, dict):
            return ("keys:" + ",".join(list(d)[:6]))[:200]
        return str(d)[:200]
    return (result.error or "")[:200]


class SkillExecutor:
    def __init__(self, registry=None, audit=None, security_log=None, approvals=None,
                 policies=None, sandbox=None, decision_log=None, runtime=None,
                 default_timeout: float = 15.0) -> None:
        # Lazy imports — break any import cycle with core.security.
        from core.security.approvals import ApprovalManager
        from core.security.policies import PolicyEngine, default_policies
        from core.security.sandbox import ThreadSandbox
        from core.security.security_log import SecurityLog
        from .audit import AuditLog
        from .registry import get_registry

        # NB: SkillRegistry defines __len__, so an empty registry is falsy — use
        # explicit None checks, never `or`, or the passed-in registry gets dropped.
        self._registry = registry if registry is not None else get_registry()
        self._audit = audit if audit is not None else AuditLog()
        self._security = security_log if security_log is not None else SecurityLog()
        self._approvals = approvals if approvals is not None else ApprovalManager()
        self._policies = policies if policies is not None else PolicyEngine(default_policies())
        self._sandbox = sandbox if sandbox is not None else ThreadSandbox()
        self._decision_log = decision_log
        self._runtime = runtime
        self._default_timeout = default_timeout
        self._metrics: dict[str, int] = defaultdict(int)

    # ── public ─────────────────────────────────────────────────────────────────
    def execute(self, skill_name: str, args: Optional[dict] = None, context=None) -> Result:
        from core.observability import new_trace_id
        from core.security.policies import PolicyEffect
        from core.security.roles import Role
        from .context import SkillContext

        args = dict(args or {})
        context = context or SkillContext.minimal()
        if context.trace_id is None:
            context.trace_id = new_trace_id()
        if context.user_role is None:
            context.user_role = Role.USER

        role = context.user_role
        trace_id = context.trace_id
        t0 = time.perf_counter()
        approved = False
        skill = None

        try:
            skill = self._registry.get(skill_name)                 # SkillNotFound
            skill.validate(args)                                   # ValidationError
            self._emit(context, "ACTION_EXECUTE", {"skill": skill_name})

            decision = self._policies.evaluate(skill, context, args)
            if decision.effect is PolicyEffect.DENY:
                raise PolicyViolation(decision.reason or "denied by policy")

            if not role.allows(skill.permission):
                raise PermissionDenied(
                    f"role '{getattr(role, 'value', role)}' lacks clearance for "
                    f"{skill.permission.name} skill '{skill.name}'"
                )

            needs_approval = (
                requires_approval(skill.permission)
                or decision.effect is PolicyEffect.REQUIRE_APPROVAL
            )
            if needs_approval:
                verdict = self._approvals.request_and_wait(skill, args, context)  # ApprovalTimeout
                if not verdict.approved:
                    raise ApprovalRejected(verdict.reason or "approval rejected")
            approved = True

            data = self._invoke(skill, context, args)
            dur = (time.perf_counter() - t0) * 1000.0
            result = SuccessResult(data=data, duration_ms=round(dur, 2),
                                   metadata={"skill": skill.name, "trace_id": trace_id})
            self._record(ok=True, skill_name=skill.name, skill=skill, context=context,
                         role=role, approved=approved, duration=dur, result=result,
                         trace_id=trace_id)
            return result

        except SkillError as e:
            dur = (time.perf_counter() - t0) * 1000.0
            result = FailureResult(str(e), error_type=type(e).__name__, duration_ms=round(dur, 2),
                                   metadata={"skill": skill_name, "trace_id": trace_id})
            self._record(ok=False, skill_name=skill_name, skill=skill, context=context,
                         role=role, approved=approved, duration=dur, result=result,
                         trace_id=trace_id, error=e)
            self._record_security(e, skill_name, context, role)
            return result

        except Exception as e:                                     # skill bug → contained
            dur = (time.perf_counter() - t0) * 1000.0
            log.exception("skill '%s' crashed", skill_name)
            result = FailureResult(str(e), error_type=type(e).__name__, duration_ms=round(dur, 2),
                                   metadata={"skill": skill_name, "trace_id": trace_id})
            self._record(ok=False, skill_name=skill_name, skill=skill, context=context,
                         role=role, approved=approved, duration=dur, result=result,
                         trace_id=trace_id, error=e)
            return result

    async def aexecute(self, skill_name: str, args: Optional[dict] = None, context=None) -> Result:
        """Async entry for callers already on the runtime loop — runs the sync
        pipeline in the default executor so the loop is never blocked."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.execute(skill_name, args, context))

    def metrics(self) -> dict:
        return dict(self._metrics)

    @property
    def registry(self):
        """The skill registry this executor resolves from (read access for
        callers that need skill metadata, e.g. risk-based deliberation)."""
        return self._registry

    # ── internals ──────────────────────────────────────────────────────────────
    def _invoke(self, skill, context, args: dict):
        timeout = skill.timeout or self._default_timeout
        if asyncio.iscoroutinefunction(skill.run):
            coro = skill.run(context, **args)
            rt = context.runtime or self._runtime
            if rt is not None and getattr(rt, "_started", False):
                fut = rt.submit_coro(coro)
                try:
                    return fut.result(timeout)
                except FuturesTimeout:
                    raise SandboxTimeout(f"'{skill.name}' exceeded {timeout}s")
            return asyncio.run(asyncio.wait_for(coro, timeout))
        # sync skill: sandbox only the dangerous ones
        if skill.risk_level >= RiskLevel.HIGH:
            return self._sandbox.run_sync(lambda: skill.run(context, **args), timeout)
        return skill.run(context, **args)

    def _record(self, *, ok, skill_name, skill, context, role, approved, duration,
                result, trace_id, error=None) -> None:
        permission = skill.permission.name if skill else None
        role_str = getattr(role, "value", str(role))
        self._audit.record(
            trace_id=trace_id, skill_name=skill_name, caller=context.caller, role=role_str,
            permission=permission, approved=approved, duration_ms=round(duration, 2),
            success=ok, error=(str(error) if error else None), result_summary=_summarize(result),
        )
        dl = context.decision_log or self._decision_log
        if dl is not None:
            try:
                dl.log(
                    trace_id=trace_id, intent=skill_name, route=["skill"],
                    skills_invoked=[skill_name], confidence=1.0 if ok else 0.0,
                    latency_ms=int(duration), outcome="success" if ok else "failure",
                    rationale=(str(error) if error else "ok"),
                    was_autonomous=(context.caller != "user"), source="skills.executor",
                )
            except Exception:
                log.debug("decision-log write failed", exc_info=True)
        self._metrics["executions"] += 1
        self._metrics["success" if ok else "failure"] += 1
        self._emit(context, "UI_UPDATE" if ok else "MODULE_ERROR",
                   {"skill": skill_name, "ok": ok})

    def _record_security(self, error, skill_name, context, role) -> None:
        mapping = _SECURITY_EVENT.get(type(error).__name__)
        if not mapping:
            return
        event_type, severity = mapping
        self._security.record(
            event_type=event_type, severity=severity, trace_id=context.trace_id,
            skill_name=skill_name, caller=context.caller,
            role=getattr(role, "value", str(role)), detail=str(error),
        )

    def _emit(self, context, signal_name: str, data: dict) -> None:
        rt = context.runtime or self._runtime
        if rt is None:
            return
        try:
            from core.infra.friday_signal import Signal
            sig = getattr(Signal, signal_name, None)
            if sig is not None:
                rt.emit(sig, data=data, source="skills")
        except Exception:
            pass
