"""
M50 — the nervous system: nerves sense, reflexes self-heal, the brain gets a
clean picture and gated access.

Like the peripheral nervous system: between every module and the brain sits a
nerve that probes health, fires a SAFE local reflex to fix problems before the
brain has to think, and relays only the healed status upward. Reflexes are
whitelisted (recover/reset/reconnect/reload), rate-limited, and never
destructive; a nerve never raises.
"""

from __future__ import annotations

from core.nervous import NervousSystem, reflex
from core.nervous.nerve import ModuleNerve, NerveStatus
from core.nervous.reflexes import SAFE_REFLEXES, derive_reflex


class _Flaky:
    def __init__(self):
        self.broken = True
        self.resets = 0

    def health(self):
        return {"status": "degraded" if self.broken else "ok"}

    @reflex
    def reset(self):                    # explicitly opted-in safe reflex
        self.resets += 1
        self.broken = False


class _Healthy:
    def health(self):
        return {"status": "ok"}


class _Unhealable:
    def health(self):
        return {"status": "error"}       # exposes no safe reflex method


# ── the reflex arc ─────────────────────────────────────────────────────────────

def test_healthy_module_is_ok_no_reflex():
    n = ModuleNerve("h", _Healthy().health)
    r = n.check()
    assert r.status is NerveStatus.OK and not r.healed


def test_degraded_module_self_heals():
    m = _Flaky()
    n = ModuleNerve("f", m.health, heal=derive_reflex(m))
    r = n.check()
    assert r.status is NerveStatus.HEALED and r.healed
    assert r.reflex == "reset" and m.resets == 1
    # once healed it probes clean, no further reflex
    assert n.check().status is NerveStatus.OK


def test_unhealable_is_reported_degraded_not_hidden():
    n = ModuleNerve("u", _Unhealable().health, heal=derive_reflex(_Unhealable()))
    r = n.check()
    assert r.status is NerveStatus.DEGRADED and not r.healed


def test_strained_is_usable_not_a_fault():
    # "strained" (RAM pressure, warming up) means up-but-loaded — the module is
    # still reachable, no reflex fires, and it never drags the body to degraded
    class _Strained:
        def health(self):
            return {"status": "strained"}
        @reflex
        def reset(self):
            raise AssertionError("a reflex fired on a merely-strained module!")
    n = ModuleNerve("s", _Strained().health, heal=derive_reflex(_Strained()))
    r = n.check()
    assert r.status is NerveStatus.STRAINED and r.usable


def test_a_probe_that_raises_is_a_fault():
    def boom():
        raise RuntimeError("sensor dead")
    r = ModuleNerve("b", boom).check()
    assert r.status is NerveStatus.DEGRADED
    assert "probe raised" in r.detail


def test_reflex_that_fails_leaves_module_failed():
    class _StillBroken:
        def health(self):
            return {"status": "error"}
        @reflex
        def reset(self):
            pass                          # reflex runs but doesn't fix anything
    m = _StillBroken()
    n = ModuleNerve("s", m.health, heal=derive_reflex(m))
    r = n.check()
    assert r.status is NerveStatus.FAILED and not r.healed


def test_healing_is_rate_limited():
    # a module that breaks again immediately must not heal-loop forever
    class _Rebreaks:
        def __init__(self):
            self.reset_calls = 0
        def health(self):
            return {"status": "error"}    # always broken
        @reflex
        def reset(self):
            self.reset_calls += 1
    m = _Rebreaks()
    n = ModuleNerve("r", m.health, heal=derive_reflex(m), max_heals=3, window_s=1000)
    for _ in range(10):
        n.check(now=1000.0)
    assert m.reset_calls == 3             # capped, no infinite reflex loop
    assert n.check(now=1000.0).status is NerveStatus.DEGRADED


# ── reflex safety (whitelist only) ─────────────────────────────────────────────

def test_only_whitelisted_methods_are_reflexes():
    class _Dangerous:
        def health(self):
            return {"status": "error"}
        def restart_pc(self, delay=0):    # destructive — must NEVER be a reflex
            raise AssertionError("a nerve fired a destructive method!")
        def delete_everything(self):
            raise AssertionError("a nerve fired a destructive method!")
    assert derive_reflex(_Dangerous()) is None


def test_reflex_requires_zero_args():
    class _NeedsArgs:
        def reset(self, target):          # not a safe zero-arg reflex
            pass
    assert derive_reflex(_NeedsArgs()) is None


def test_reflex_preference_order():
    # recover() is preferred over reset() when both exist
    calls = []
    class _Both:
        @reflex
        def recover(self): calls.append("recover")
        @reflex
        def reset(self): calls.append("reset")
    derive_reflex(_Both())()
    assert calls == ["recover"]


def test_unmarked_whitelisted_method_is_not_a_reflex():
    # SECURITY INVARIANT (review): a method named like a reflex but NOT
    # @reflex-marked must never auto-fire — so a future MemoryService.reset()
    # that wipes the store can't silently become an autonomous reflex.
    class _DataOwner:
        def health(self):
            return {"status": "error"}
        def reset(self):                  # named right, NOT marked
            raise AssertionError("an unmarked reset() was auto-fired!")
    assert derive_reflex(_DataOwner()) is None


def test_data_owning_registered_modules_expose_no_reflex():
    # regression guard: the real data-owning modules must not auto-heal.
    # If someone later adds a @reflex reset() to one of these, this trips.
    from core.memory.service import MemoryService
    from core.brains.memory.knowledge_graph import KnowledgeGraph
    from core.memory import HashingEmbedder, MemoryStore, NumpyFlatIndex
    import tempfile
    from pathlib import Path
    emb = HashingEmbedder()
    mem = MemoryService(store=MemoryStore(Path(tempfile.mkdtemp()) / "m.db"),
                        index=NumpyFlatIndex(emb.dim), embedder=emb)
    assert derive_reflex(mem) is None
    assert derive_reflex(KnowledgeGraph()) is None


# ── the system: pulse, aggregate, gated access ─────────────────────────────────

def test_pulse_heals_and_reports_the_whole_picture():
    ns = NervousSystem()
    flaky, healthy, broken = _Flaky(), _Healthy(), _Unhealable()
    ns.register("flaky", flaky)
    ns.register("healthy", healthy)
    ns.register("broken", broken)
    pic = ns.pulse()
    # a still-broken module is the honest headline even though flaky healed
    assert pic["overall"] == "degraded"
    assert "flaky" in pic["healed"] and "broken" in pic["degraded"]
    assert pic["reports"]["flaky"]["status"] == "healed"


def test_overall_is_healing_when_nothing_remains_broken():
    ns = NervousSystem()
    ns.register("flaky", _Flaky())               # heals; nothing else broken
    pic = ns.pulse()
    assert pic["overall"] == "healing" and not pic["degraded"]


def test_brain_reaches_only_usable_modules():
    ns = NervousSystem()
    flaky, broken = _Flaky(), _Unhealable()
    ns.register("flaky", flaky)
    ns.register("broken", broken)
    ns.pulse()
    assert ns.access("flaky") is flaky           # self-healed → reachable
    assert ns.access("broken") is None           # degraded → the brain can't touch it
    assert ns.access("missing") is None


def test_strained_module_stays_reachable_and_body_is_not_degraded():
    class _Strained:
        def health(self):
            return {"status": "strained"}
    ns = NervousSystem()
    s = _Strained()
    ns.register("busy", s)
    pic = ns.pulse()
    assert pic["overall"] == "strained" and "busy" in pic["strained"]
    assert not pic["degraded"]
    assert ns.access("busy") is s                # a loaded module is still reachable


def test_report_sink_receives_the_healed_picture():
    seen = []
    ns = NervousSystem(report_sink=seen.append)
    ns.register("flaky", _Flaky())
    ns.pulse()
    assert seen and seen[-1]["overall"] == "healing"


def test_modules_without_a_health_signal_are_skipped():
    ns = NervousSystem()
    assert ns.register("nothing", object()) is None
    assert ns.status()["nerves"] == 0


def test_register_all_counts_nerved_modules():
    ns = NervousSystem()
    n = ns.register_all({"a": _Healthy(), "b": _Flaky(), "c": object(), "d": None})
    assert n == 2                                 # only the two with health()


# ── the brain reaches modules only through the nervous system (M50 wiring) ──────

def test_executive_reaches_only_healthy_modules_through_nerves():
    from core.brains.executive.brain import ExecutiveBrain
    ns = NervousSystem()
    good, bad = _Healthy(), _Unhealable()
    ns.register("good", good)
    ns.register("bad", bad)
    ns.pulse()
    ex = ExecutiveBrain()
    ex._nervous = ns                              # wired at boot's nervous stage
    assert ex.reach("good") is good               # healthy → reachable
    assert ex.reach("bad") is None                # broken → the brain can't touch it
    assert ex.body_status()["overall"] in ("ok", "degraded", "healing")
