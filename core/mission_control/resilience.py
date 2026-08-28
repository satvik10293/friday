"""
core/mission_control/resilience.py — FRIDAY 4.0 (M10)
Graceful-degradation primitives. Mission Control must keep operating when any
subsystem fails; `safe_call` runs a provider and, on any exception, returns a
`Degraded` marker instead of propagating — so one broken panel never takes down
the cockpit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("friday.mission_control.resilience")


@dataclass
class Degraded:
    system: str
    error: str
    status: str = "degraded"

    def to_dict(self) -> dict:
        return {"status": self.status, "system": self.system, "error": self.error}


def safe_call(system: str, fn: Callable[[], Any], *, default: Any = None) -> Any:
    """Run `fn`; on any failure return `default` (or a Degraded marker). Never
    raises. The contract that keeps Mission Control alive."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 — degradation is the whole point
        log.debug("subsystem '%s' degraded: %s", system, e)
        return default if default is not None else Degraded(system=system, error=str(e))


def is_degraded(value: Any) -> bool:
    return isinstance(value, Degraded) or (
        isinstance(value, dict) and value.get("status") == "degraded")
