"""
core/nervous/nerve.py — FRIDAY V3 (M50)
A single nerve: the reflex arc for one module. sense → (reflex) → relay.
Pure, thread-safe, never-raises.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger("friday.nervous.nerve")

_HEALTHY = {"ok", "healthy", "ready", "nominal", "online", "placeholder"}
# soft states: the module is UP and usable, just not at full capacity (under
# load, warming up, consolidating). Honest to surface, but NOT a fault — no
# reflex fixes RAM pressure, and it must not drag the whole body to "degraded".
_SOFT = {"strained", "busy", "warming", "warming_up", "limited", "loading",
         "consolidating", "throttled", "degraded_but_working"}


class NerveStatus(str, Enum):
    OK = "ok"              # healthy on probe
    HEALED = "healed"      # was unhealthy, a reflex fixed it
    STRAINED = "strained"  # up + usable but under load — noted, not a fault
    DEGRADED = "degraded"  # a real fault: heal budget spent / no reflex
    FAILED = "failed"      # a reflex ran but the module is still unhealthy


@dataclass
class NerveReport:
    name: str
    status: NerveStatus
    healed: bool = False
    heal_count: int = 0
    detail: str = ""
    reflex: str = ""
    ts: float = field(default_factory=time.time)

    @property
    def usable(self) -> bool:
        """Whether the brain may reach this module — healthy, self-healed, or
        merely strained (up and working, just under load)."""
        return self.status in (NerveStatus.OK, NerveStatus.HEALED,
                               NerveStatus.STRAINED)

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status.value,
                "healed": self.healed, "heal_count": self.heal_count,
                "reflex": self.reflex, "detail": self.detail[:200]}


def _classify(probe_result) -> tuple[str, str]:
    """Normalise a probe result to (class, detail) where class is
    'ok' | 'soft' | 'fault'. Accepts a health/status dict, a bool, or None."""
    if probe_result is None:
        return "fault", "no health signal"
    if isinstance(probe_result, bool):
        return ("ok", "") if probe_result else ("fault", "unhealthy")
    if isinstance(probe_result, dict):
        status = str(probe_result.get("status", "")).lower()
        if status:
            if status in _HEALTHY:
                return "ok", status
            if status in _SOFT:
                return "soft", status
            return "fault", status
        # no explicit status key → an "error"/"failed" flag is a fault
        if probe_result.get("error") or probe_result.get("failed"):
            return "fault", str(probe_result.get("error") or "failed")
        return "ok", "ok"
    return "ok", str(probe_result)[:80]


class ModuleNerve:
    """The reflex arc for one module. `probe` returns its health; when unhealthy
    and a `heal` reflex is available (and within budget), the reflex fires and
    the module is re-probed. Rate-limited so a broken module can't heal-loop."""

    def __init__(self, name: str, probe: Callable[[], object], *,
                 heal: Optional[Callable[[], object]] = None,
                 max_heals: int = 3, window_s: float = 300.0) -> None:
        self.name = name
        self._probe = probe
        self._heal = heal
        self._max_heals = max_heals
        self._window_s = window_s
        self._heal_times: list[float] = []
        self._lock = threading.Lock()
        self.last: Optional[NerveReport] = None

    # ── the reflex arc (never raises) ────────────────────────────────────────────
    def check(self, *, now: Optional[float] = None) -> NerveReport:
        now = now if now is not None else time.time()
        cls, detail = self._sense()
        if cls == "ok":
            return self._record(NerveReport(self.name, NerveStatus.OK, detail=detail))
        if cls == "soft":
            # up and usable, just under load — surface it, but never reflex
            # (nothing to fix) and never count it as a fault
            return self._record(NerveReport(self.name, NerveStatus.STRAINED,
                                            detail=detail))

        # a real fault → reflex, if we have one and haven't been healing too often
        if self._heal is None:
            return self._record(NerveReport(self.name, NerveStatus.DEGRADED,
                                            detail=detail))
        if not self._heal_budget(now):
            return self._record(NerveReport(self.name, NerveStatus.DEGRADED,
                                            heal_count=len(self._heal_times),
                                            detail="heal budget spent: " + detail))
        reflex_name = self._fire_reflex(now)
        cls2, detail2 = self._sense()
        healed = cls2 in ("ok", "soft")            # back to usable = healed
        status = NerveStatus.HEALED if healed else NerveStatus.FAILED
        return self._record(NerveReport(
            self.name, status, healed=healed, heal_count=len(self._heal_times),
            reflex=reflex_name, detail=detail2 or detail))

    # ── internals ────────────────────────────────────────────────────────────────
    def _sense(self) -> tuple[str, str]:
        try:
            return _classify(self._probe())
        except Exception as e:  # noqa: BLE001 — a probe that throws IS a fault
            return "fault", f"probe raised: {type(e).__name__}"

    def _heal_budget(self, now: float) -> bool:
        cutoff = now - self._window_s
        self._heal_times = [t for t in self._heal_times if t >= cutoff]
        return len(self._heal_times) < self._max_heals

    def _fire_reflex(self, now: float) -> str:
        with self._lock:
            self._heal_times.append(now)
        try:
            result = self._heal()
            return str(result) if result else "reflex"
        except Exception as e:  # noqa: BLE001 — a failed reflex is not fatal
            log.debug("reflex for %s raised", self.name, exc_info=True)
            return f"reflex_error:{type(e).__name__}"

    def _record(self, report: NerveReport) -> NerveReport:
        self.last = report
        if report.status is NerveStatus.HEALED:
            log.info("nerve %s: self-healed via %s", self.name, report.reflex)
        elif report.status in (NerveStatus.DEGRADED, NerveStatus.FAILED):
            log.warning("nerve %s: %s (%s)", self.name, report.status.value,
                        report.detail)
        return report
