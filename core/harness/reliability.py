"""
core/harness/reliability.py — FRIDAY harness (reliability primitives)

The harness must never assume a model, API, or agent will work. This module is
the small set of primitives that make "call something that might fail" safe and
uniform: a retry policy with exponential backoff, a circuit breaker with
half-open recovery, a per-call timeout, and `reliable_call` which composes all
three around any async operation.

Design notes:
    · A provider returns `GenResult(ok=False)` rather than raising, so failure
      here is defined by a `is_success` predicate (default: truthy `.ok`) OR an
      exception OR a timeout — all three count as one failed attempt.
    · The circuit breaker protects a *specific* backend: after N failures it
      opens (fail fast, no wasted calls), and after a cooldown it goes half-open
      to let a single probe test recovery. One success closes it again.
    · Nothing here logs on its own; callers pass `on_event` to route events into
      the DecisionLog / structured logs without coupling this module to them.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional


class CircuitOpenError(RuntimeError):
    """Raised by `reliable_call` when the breaker is open and rejects the call."""


class CircuitState(str, Enum):
    CLOSED = "closed"          # healthy, calls pass through
    OPEN = "open"              # failing, calls rejected until cooldown elapses
    HALF_OPEN = "half_open"    # cooldown elapsed, one probe allowed


@dataclass
class RetryPolicy:
    max_attempts: int = 2
    base_delay_s: float = 0.2
    backoff: float = 2.0
    max_delay_s: float = 5.0
    jitter: bool = False        # off by default so tests are deterministic

    def delay(self, attempt: int) -> float:
        """Backoff before the retry that follows `attempt` (1-based)."""
        d = min(self.base_delay_s * (self.backoff ** (attempt - 1)), self.max_delay_s)
        if self.jitter:
            d *= 0.5 + random.random()
        return d


@dataclass
class CircuitBreaker:
    """Per-backend breaker. Not thread-safe by design — the harness drives it
    from a single event loop; wrap in a lock only if shared across threads."""
    fail_threshold: int = 3
    reset_timeout_s: float = 30.0
    _failures: int = 0
    _state: CircuitState = field(default=CircuitState.CLOSED)
    _opened_at: float = 0.0

    def allow(self) -> bool:
        """Whether a call may proceed now. Transitions OPEN → HALF_OPEN once the
        cooldown has elapsed (permitting exactly one probe)."""
        if self._state is CircuitState.OPEN:
            if (time.monotonic() - self._opened_at) >= self.reset_timeout_s:
                self._state = CircuitState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        # A failure while probing (half-open) re-opens immediately.
        if self._state is CircuitState.HALF_OPEN:
            self._trip()
            return
        self._failures += 1
        if self._failures >= self.fail_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = time.monotonic()

    @property
    def state(self) -> str:
        return self._state.value

    def to_dict(self) -> dict:
        return {"state": self._state.value, "failures": self._failures,
                "fail_threshold": self.fail_threshold}


def _default_is_success(result) -> bool:
    return bool(getattr(result, "ok", True))


async def reliable_call(
    fn: Callable[[], Awaitable],
    *,
    retry: Optional[RetryPolicy] = None,
    breaker: Optional[CircuitBreaker] = None,
    timeout_s: Optional[float] = None,
    is_success: Callable[[object], bool] = _default_is_success,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> object:
    """Run `fn()` (a zero-arg async callable) with timeout + retry + breaker.

    Returns the successful result, or the last failed result if every attempt
    failed. Raises `CircuitOpenError` only when the breaker rejects the very
    first attempt (fail-fast) and there is no prior result to return.
    """
    retry = retry or RetryPolicy()

    def emit(event: str, **data) -> None:
        if on_event is not None:
            try:
                on_event(event, data)
            except Exception:  # noqa: BLE001 — observability must never break the call
                pass

    last = None
    for attempt in range(1, retry.max_attempts + 1):
        if breaker is not None and not breaker.allow():
            emit("circuit_open", attempt=attempt, state=breaker.state)
            if last is not None:
                return last
            raise CircuitOpenError("circuit open; refusing call")

        try:
            if timeout_s is not None:
                result = await asyncio.wait_for(fn(), timeout_s)
            else:
                result = await fn()
            failed_reason = "" if is_success(result) else "unsuccessful_result"
        except asyncio.TimeoutError:
            result, failed_reason = None, f"timeout>{timeout_s}s"
        except Exception as e:  # noqa: BLE001 — an exception is just a failed attempt
            result, failed_reason = None, f"exception:{e}"

        if not failed_reason:
            if breaker is not None:
                breaker.record_success()
            emit("success", attempt=attempt)
            return result

        if breaker is not None:
            breaker.record_failure()
        if result is not None:
            last = result
        emit("attempt_failed", attempt=attempt, reason=failed_reason,
             state=breaker.state if breaker else None)

        if attempt < retry.max_attempts:
            await asyncio.sleep(retry.delay(attempt))

    emit("exhausted", attempts=retry.max_attempts)
    return last
