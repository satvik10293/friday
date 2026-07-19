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
from enum import Enum
from typing import Callable, Optional

from .nerve import ModuleNerve, NerveReport, NerveStatus
from .reflexes import derive_reflex

log = logging.getLogger("friday.nervous.system")


class NervousEvent(str, Enum):
    MODULE_RELOADED = "nervous.module_reloaded"


class NervousSystem:
    def __init__(self, *, report_sink: Optional[Callable[[dict], None]] = None,
                 container=None) -> None:
        # report_sink relays the consolidated picture upward (e.g. to the
        # Executive / report bus) after every pulse. `container` (the DI
        # kernel) lets a reloaded module REPLACE its live service instance so
        # consumers get the fresh one without an app restart (M59).
        self._report_sink = report_sink
        self._container = container
        self._runtime = None                     # set by attach(); event emits
        self._nerves: dict[str, ModuleNerve] = {}
        self._modules: dict[str, object] = {}
        self._factories: dict[str, Callable[[], object]] = {}
        self._reload_counts: dict[str, int] = {}
        self.max_reloads = 2                     # per module, per process
        self._lock = threading.Lock()
        self._pulses = 0
        self._heals = 0
        self._reloads = 0
        self._last_picture: dict = {}

    # ── wiring ───────────────────────────────────────────────────────────────────
    def register(self, name: str, module: object, *,
                 probe: Optional[Callable[[], object]] = None,
                 heal: Optional[Callable[[], object]] = None,
                 factory: Optional[Callable[[], object]] = None,
                 max_heals: int = 3) -> Optional[ModuleNerve]:
        """Grow a nerve for a module. Probe + reflex are auto-derived from the
        module's own health()/status() and safe recovery methods unless given.
        A module with no health signal at all is skipped (nothing to sense).

        `factory` (M59, OPT-IN) enables the strongest recovery: when the
        module stays broken after its reflex (FAILED/DEGRADED), the nervous
        system rebuilds it from the factory and swaps the live instance —
        module reload without an app restart. Explicitly opt-in per module,
        never derived: data-owning modules must never be silently rebuilt
        (the M50 invariant)."""
        probe = probe or _derive_probe(module)
        if probe is None:
            log.debug("no health signal on %s — not nerved", name)
            return None
        nerve = ModuleNerve(name, probe, heal=heal or derive_reflex(module),
                            max_heals=max_heals)
        with self._lock:
            self._nerves[name] = nerve
            self._modules[name] = module
            if factory is not None:
                self._factories[name] = factory
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
            # the strongest recovery (M59): a module still broken after its
            # reflex, with an opt-in factory, is REBUILT and swapped live
            if report.status in (NerveStatus.FAILED, NerveStatus.DEGRADED):
                reloaded = self._try_reload(nerve.name)
                if reloaded is not None:
                    report = reloaded
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

    # ── module reload (M59): rebuild + live-swap, opt-in, budgeted ───────────────
    def _try_reload(self, name: str) -> Optional[NerveReport]:
        """Rebuild a still-broken module from its opt-in factory, verify the
        NEW instance is healthy BEFORE swapping, then replace it everywhere
        (module map, nerve, DI container) and announce the swap. Returns the
        healed report, or None (no factory / budget spent / rebuild failed —
        the old instance stays, degraded but present). Never raises."""
        with self._lock:
            factory = self._factories.get(name)
            count = self._reload_counts.get(name, 0)
        if factory is None or count >= self.max_reloads:
            return None
        with self._lock:                        # a failed attempt spends budget
            self._reload_counts[name] = count + 1
        try:
            new_module = factory()
        except Exception:  # noqa: BLE001 — a broken factory must not break the pulse
            log.warning("reload factory for %s failed", name, exc_info=True)
            return None
        if new_module is None:
            return None
        probe = _derive_probe(new_module)
        if probe is None:
            return None
        new_nerve = ModuleNerve(name, probe, heal=derive_reflex(new_module))
        report = new_nerve.check()
        if not report.usable:                   # verify BEFORE swap — never
            log.warning("reloaded %s is still unhealthy — keeping the old "
                        "instance", name)       # trade a limping module for a dead one
            return None
        with self._lock:
            self._modules[name] = new_module
            self._nerves[name] = new_nerve
            self._reloads += 1
        if self._container is not None:
            try:                                # consumers resolve the fresh one
                self._container.replace(name, new_module)
            except Exception:  # noqa: BLE001
                log.debug("container replace failed for %s", name, exc_info=True)
        if self._runtime is not None:
            try:                                # holders of direct refs can react
                self._runtime.emit(NervousEvent.MODULE_RELOADED,
                                   data={"module": name}, source="nervous")
            except Exception:  # noqa: BLE001
                log.debug("reload event emit failed", exc_info=True)
        log.info("module %s rebuilt and live-swapped (reload %d/%d)",
                 name, count + 1, self.max_reloads)
        return NerveReport(name=name, status=NerveStatus.HEALED, healed=True,
                           reflex="reload",
                           detail="module rebuilt + live-swapped")

    def picture(self) -> dict:
        return dict(self._last_picture)

    def attach(self, runtime, *, every_s: float = 30.0) -> bool:
        """Pulse periodically on the runtime scheduler (autonomic — it just
        keeps beating). Best-effort."""
        self._runtime = runtime                 # reload events emit here (M59)
        try:
            # the Runtime's real API is schedule(name, fn, every); older/other
            # schedulers expose every()/add_interval() — try all.
            if hasattr(runtime, "schedule"):
                runtime.schedule("nervous_pulse", self.pulse, every_s)
                return True
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
                "total_heals": self._heals, "reloads": self._reloads,
                "reloadable": len(self._factories),
                "overall": self._last_picture.get("overall", "unknown")}


def _derive_probe(module) -> Optional[Callable[[], object]]:
    """A module's probe is its own health() (preferred) or status()."""
    for name in ("health", "status"):
        fn = getattr(module, name, None)
        if callable(fn):
            return fn
    return None
