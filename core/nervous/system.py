"""
core/nervous/system.py — FRIDAY V3 (M50)
The Nervous System: one nerve per module, pulsed together. Each pulse senses
every module, fires reflexes to self-heal what it can, and relays a single
consolidated, healed health picture to the brain (the Executive). The brain
reaches modules only through `access()` — so it never touches a module a nerve
knows is broken.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .nerve import ModuleNerve, NerveReport, NerveStatus
from .reflexes import derive_reflex

log = logging.getLogger("friday.nervous.system")


class NervousSystem:
    def __init__(self, *, report_sink: Optional[Callable[[dict], None]] = None) -> None:
        # report_sink relays the consolidated picture upward (e.g. to the
        # Executive / report bus) after every pulse.
        self._report_sink = report_sink
        self._nerves: dict[str, ModuleNerve] = {}
        self._modules: dict[str, object] = {}
        self._lock = threading.Lock()
        self._pulses = 0
        self._heals = 0
        self._last_picture: dict = {}

    # ── wiring ───────────────────────────────────────────────────────────────────
    def register(self, name: str, module: object, *,
                 probe: Optional[Callable[[], object]] = None,
                 heal: Optional[Callable[[], object]] = None,
                 max_heals: int = 3) -> Optional[ModuleNerve]:
        """Grow a nerve for a module. Probe + reflex are auto-derived from the
        module's own health()/status() and safe recovery methods unless given.
        A module with no health signal at all is skipped (nothing to sense)."""
        probe = probe or _derive_probe(module)
        if probe is None:
            log.debug("no health signal on %s — not nerved", name)
            return None
        nerve = ModuleNerve(name, probe, heal=heal or derive_reflex(module),
                            max_heals=max_heals)
        with self._lock:
            self._nerves[name] = nerve
            self._modules[name] = module
        return nerve

    def register_all(self, modules: dict) -> int:
        """Nerve every {name: module} that has a health signal. Returns the count
        actually nerved."""
        n = 0
        for name, module in (modules or {}).items():
            if module is not None and self.register(name, module) is not None:
                n += 1
        return n

    # ── the pulse (sense → reflex → relay) ───────────────────────────────────────
    def pulse(self, *, now: Optional[float] = None) -> dict:
        now = now if now is not None else time.time()
        with self._lock:
            nerves = list(self._nerves.values())
        reports: list[NerveReport] = []
        for nerve in nerves:
            report = nerve.check(now=now)
            reports.append(report)
            if report.status is NerveStatus.HEALED:
                self._heals += 1
        self._pulses += 1
        picture = self._aggregate(reports)
        self._last_picture = picture
        if self._report_sink is not None:
            try:
                self._report_sink(picture)
            except Exception:  # noqa: BLE001 — relaying up must never break the pulse
                log.debug("report sink failed", exc_info=True)
        return picture

    def _aggregate(self, reports: list[NerveReport]) -> dict:
        by_status: dict[str, int] = {}
        healed_now, degraded, strained = [], [], []
        for r in reports:
            by_status[r.status.value] = by_status.get(r.status.value, 0) + 1
            if r.status is NerveStatus.HEALED:
                healed_now.append(r.name)
            elif r.status in (NerveStatus.DEGRADED, NerveStatus.FAILED):
                degraded.append(r.name)
            elif r.status is NerveStatus.STRAINED:
                strained.append(r.name)
        # overall, most urgent first: a real fault → "degraded"; a reflex fired
        # → "healing"; something under load → "strained"; else "ok". A strained
        # module (RAM pressure, warming up) is NOT a degraded body.
        if degraded:
            overall = "degraded"
        elif healed_now:
            overall = "healing"
        elif strained:
            overall = "strained"
        else:
            overall = "ok"
        return {"overall": overall, "modules": len(reports),
                "by_status": by_status, "healed": healed_now,
                "degraded": degraded, "strained": strained,
                "reports": {r.name: r.to_dict() for r in reports},
                "pulses": self._pulses, "total_heals": self._heals}

    # ── the brain's gated access ─────────────────────────────────────────────────
    def access(self, name: str):
        """Hand the brain a module ONLY if its nerve last saw it usable (healthy
        or self-healed). A degraded module returns None — the brain can't reach
        something the nervous system knows is broken."""
        with self._lock:
            nerve = self._nerves.get(name)
            module = self._modules.get(name)
        if nerve is None or module is None:
            return None
        if nerve.last is None:
            nerve.check()
        return module if (nerve.last and nerve.last.usable) else None

    def picture(self) -> dict:
        return dict(self._last_picture)

    def attach(self, runtime, *, every_s: float = 30.0) -> bool:
        """Pulse periodically on the runtime scheduler (autonomic — it just
        keeps beating). Best-effort."""
        try:
            scheduler = getattr(runtime, "scheduler", None) or runtime
            for meth in ("every", "schedule_every", "add_interval"):
                fn = getattr(scheduler, meth, None)
                if callable(fn):
                    fn(every_s, self.pulse)
                    return True
        except Exception:  # noqa: BLE001
            log.debug("nervous system attach failed", exc_info=True)
        return False

    def status(self) -> dict:
        return {"nerves": len(self._nerves), "pulses": self._pulses,
                "total_heals": self._heals, "overall": self._last_picture.get(
                    "overall", "unknown")}


def _derive_probe(module) -> Optional[Callable[[], object]]:
    """A module's probe is its own health() (preferred) or status()."""
    for name in ("health", "status"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    return None
