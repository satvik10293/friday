"""
core/nervous/reflexes.py — FRIDAY V3 (M50)
The reflex library: the SAFE local recovery actions a nerve may fire.

A reflex must be conservative — idempotent, non-destructive, cheap. It resets a
stuck state, reconnects a dropped link, re-resolves a service, reloads a light
component. It NEVER does anything a brain should decide (no PC restart, no data
loss, no external effect). That safety is enforced by a WHITELIST: only these
exact zero-argument method names are ever auto-called on a module.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger("friday.nervous.reflex")

# the ONLY method names a nerve may auto-invoke to heal a module. Each must be a
# safe, idempotent, zero-argument recovery. Ordered by preference (a dedicated
# recover() beats a blunt reset()). NOTE: names like restart_pc / shutdown /
# delete are deliberately absent — those are decisions, not reflexes.
SAFE_REFLEXES = ("recover", "reset", "reconnect", "reload")

# ENFORCED INVARIANT (security review, M50): a method being NAMED like a reflex
# is not enough — it must also be explicitly opted in with @reflex. So a future
# `MemoryService.reset()` that wipes the store can never silently become an
# auto-fired reflex on an unattended timer; marking a method @reflex is a
# deliberate, reviewable act that asserts "this is safe to fire autonomously".
_REFLEX_MARK = "__friday_reflex__"


def reflex(method):
    """Mark a zero-argument recovery method as safe for the nervous system to
    fire autonomously. Only @reflex-marked, whitelisted, zero-arg methods are
    ever auto-invoked."""
    setattr(method, _REFLEX_MARK, True)
    return method


def _is_marked(method) -> bool:
    return bool(getattr(method, _REFLEX_MARK, False))


def _is_safe_zero_arg(method) -> bool:
    """A reflex candidate must be callable with no required arguments — so a
    reflex can never be tricked into calling something that needs (dangerous)
    parameters."""
    if not callable(method):
        return False
    try:
        import inspect
        sig = inspect.signature(method)
        for p in sig.parameters.values():
            if p.default is inspect.Parameter.empty and p.kind in (
                    p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
                return False
        return True
    except (TypeError, ValueError):
        return True   # builtins without a signature — treat as zero-arg-callable


def derive_reflex(module) -> Optional[Callable[[], object]]:
    """Find the safest recovery method the module exposes, or None. A method is
    only a reflex if it is (1) whitelisted by name, (2) explicitly @reflex-
    marked, and (3) callable with no required args — all three, so a
    coincidentally-named or unmarked method is never auto-fired."""
    if module is None:
        return None
    for name in SAFE_REFLEXES:
        method = getattr(module, name, None)
        if method is not None and _is_marked(method) and _is_safe_zero_arg(method):
            def fire(_m=method, _n=name):
                _m()
                return _n
            fire.__name__ = f"reflex_{name}"
            return fire
    return None


def resolve_service_reflex(container, name: str) -> Optional[Callable[[], object]]:
    """A reflex that re-resolves a service from the DI container — for a module
    whose handle went stale (the M45 lazy-resolve pattern, as a reflex)."""
    if container is None:
        return None
    getter = getattr(container, "try_get", None)
    if not callable(getter):
        return None

    def reflex():
        svc = getter(name)
        return f"re-resolved:{name}" if svc is not None else "unresolved"
    reflex.__name__ = f"reflex_resolve_{name}"
    return reflex
