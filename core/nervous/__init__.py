"""
core/nervous/ — FRIDAY V3 (M50) The Nervous System.

Between every module and the brain sits a NERVE. Like the peripheral nervous
system, a nerve does three things before the brain ever has to think:

    sense   — probe the module's health (health()/status())
    reflex  — if something's wrong, FIX IT LOCALLY (a safe, conservative
              recovery: reset / reconnect / reload / recover), the way a hand
              pulls back from heat before the brain decides anything
    relay   — report the HEALED status upward, so the Executive always sees a
              true, self-corrected picture and reaches only healthy modules

Reflexes are strictly safe: only idempotent, non-destructive recovery methods
are ever called, healing is rate-limited (no reflex loops), and a nerve never
raises — a module that can't be healed is reported degraded, not hidden.

    from core.nervous import NervousSystem
    ns = NervousSystem()
    ns.register("memory", memory_service)     # auto-derives probe + reflex
    picture = ns.pulse()                       # sense → reflex → relay
    healthy = ns.access("memory")              # brain's gated handle
"""

from __future__ import annotations

from .nerve import ModuleNerve, NerveReport, NerveStatus
from .reflexes import SAFE_REFLEXES, derive_reflex, reflex
from .system import NervousSystem

__all__ = ["ModuleNerve", "NerveReport", "NerveStatus", "NervousSystem",
           "SAFE_REFLEXES", "derive_reflex", "reflex"]
