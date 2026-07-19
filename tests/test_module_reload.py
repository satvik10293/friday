"""
Safe module reload without an app restart (M59, extends the M50 nervous system).

The strongest recovery tier: a module still broken after its reflex, with an
OPT-IN factory, is rebuilt, verified healthy, and live-swapped — in the module
map, the nerve, and the DI container — so consumers get the fresh instance
while the app keeps running. Invariants pinned here:
· opt-in only (no factory → no reload; the M50 no-destructive-auto-heal rule)
· verify BEFORE swap (an unhealthy rebuild never replaces a limping module)
· budgeted (a crash-looping module cannot thrash rebuilds forever)
· the container serves the fresh instance; an event announces the swap
"""

from __future__ import annotations

from core.nervous.system import NervousEvent, NervousSystem
from core.services.container import ServiceContainer


class _Broken:
    """Unhealthy, no reflex — the reload candidate."""

    def health(self):
        return {"status": "error", "error": "wedged"}


class _Healthy:
    def health(self):
        return {"status": "ok"}


class _Runtime:
    def __init__(self):
        self.events = []

    def emit(self, signal, data=None, source=""):
        self.events.append((signal, data))


# ── container.replace ─────────────────────────────────────────────────────────

def test_container_replace_swaps_a_live_instance():
    c = ServiceContainer()
    old, new = _Broken(), _Healthy()
    c.register("svc", old)
    assert c.replace("svc", new) is True
    assert c.get("svc") is new                   # consumers resolve the fresh one


def test_container_replace_never_introduces_services():
    c = ServiceContainer()
    assert c.replace("ghost", _Healthy()) is False
    assert c.try_get("ghost") is None


# ── the reload arc ────────────────────────────────────────────────────────────

def test_broken_module_with_factory_is_rebuilt_and_live_swapped():
    container = ServiceContainer()
    broken = _Broken()
    container.register("wedged", broken)
    runtime = _Runtime()

    ns = NervousSystem(container=container)
    ns._runtime = runtime
    ns.register("wedged", broken, factory=_Healthy)

    picture = ns.pulse()
    report = picture["reports"]["wedged"]
    assert report["status"] == "healed" and report["reflex"] == "reload"
    assert isinstance(container.get("wedged"), _Healthy)   # container swapped
    assert isinstance(ns.access("wedged"), _Healthy)       # brain gets the new one
    assert (NervousEvent.MODULE_RELOADED, {"module": "wedged"}) in runtime.events
    assert ns.status()["reloads"] == 1


def test_no_factory_means_no_reload_the_m50_invariant():
    ns = NervousSystem()
    ns.register("data_owner", _Broken())         # no factory — data-owning
    picture = ns.pulse()
    assert picture["reports"]["data_owner"]["status"] in ("degraded", "failed")
    assert ns.status()["reloads"] == 0


def test_unhealthy_rebuild_never_replaces_the_old_instance():
    container = ServiceContainer()
    broken = _Broken()
    container.register("wedged", broken)
    ns = NervousSystem(container=container)
    ns.register("wedged", broken, factory=_Broken)   # rebuilds are broken too
    picture = ns.pulse()
    assert picture["reports"]["wedged"]["status"] in ("degraded", "failed")
    assert container.get("wedged") is broken     # old instance kept


def test_reload_budget_stops_thrash():
    ns = NervousSystem()
    ns.max_reloads = 2
    builds = []

    def factory():
        builds.append(1)
        return _Broken()                          # every rebuild still broken

    ns.register("thrash", _Broken(), factory=factory)
    for _ in range(5):
        ns.pulse()
    assert len(builds) == 2                       # budget respected, no thrash


def test_reloaded_module_reports_ok_on_the_next_pulse():
    ns = NervousSystem()
    ns.register("wedged", _Broken(), factory=_Healthy)
    ns.pulse()                                    # reload happens
    second = ns.pulse()                           # fresh module, fresh nerve
    assert second["reports"]["wedged"]["status"] == "ok"
    assert second["overall"] == "ok"
