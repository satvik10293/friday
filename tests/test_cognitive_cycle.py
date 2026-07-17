"""
Coordination: every module is actually coordinated (not just wired).

The 12-brain society was BUILT in production but never ticked — nothing ran the
observe→report→coordinate→executive loop, so the Coordinator got no reports and
the Executive saw no unified picture. Now a cognitive cycle runs on the runtime
scheduler: each cycle ticks every brain and coordinates their reports to the
Executive. (Also: the nervous-system pulse must schedule via the runtime's real
schedule() API — it silently no-op'd looking for a method that doesn't exist.)
"""

from __future__ import annotations

from core.launcher.startup import StartupSequence


def test_cognitive_cycle_coordinates_the_society_to_the_executive():
    seq = StartupSequence(headless=True, start_runtime=False)
    report = seq.run()
    ex = report.components["executive"]
    coord = report.components["coordinator"]
    baseline = ex.metrics()["received"]
    for _ in range(3):
        seq._run_cognitive_cycle()          # what the runtime fires periodically
    assert ex.metrics()["received"] > baseline, \
        "brains ticked but nothing reached the Executive — society not coordinated"
    assert coord.metrics()["published"] >= 1     # Unified Situations reached the Executive


def test_cognitive_cycle_survives_a_broken_brain():
    seq = StartupSequence(headless=True, start_runtime=False)
    report = seq.run()

    class _Boom:
        name = "boom"
        def tick(self):
            raise RuntimeError("brain exploded")

    report.components["brains"]["boom_brain"] = _Boom()
    seq._run_cognitive_cycle()               # one bad brain must not stall the cycle
    # the good brains still coordinated
    assert report.components["executive"].metrics()["received"] >= 1


# ── the scheduler wiring both loops depend on ─────────────────────────────────

class _FakeRuntime:
    def __init__(self):
        self.jobs = []

    def schedule(self, name, fn, every, **kw):
        self.jobs.append((name, every))


def test_nervous_system_schedules_its_pulse_via_runtime_schedule():
    from core.nervous import NervousSystem
    rt = _FakeRuntime()
    ns = NervousSystem()
    assert ns.attach(rt, every_s=30.0) is True
    assert ("nervous_pulse", 30.0) in rt.jobs      # the real API, not a no-op


def test_start_runtime_boot_schedules_the_cognitive_cycle(monkeypatch):
    # a full non-headless-style boot with a fake runtime must register the
    # cognitive_cycle job — otherwise the society never runs
    seq = StartupSequence(headless=True, start_runtime=True)
    rt = _FakeRuntime()
    # run the coordinator stage in isolation with our fake runtime + built brains
    from core.brains import SituationReportBus, build_brains
    seq.components["report_bus"] = SituationReportBus()
    seq.components["kernel"] = None
    seq.components["brains"] = build_brains()
    seq.components["runtime"] = rt
    seq._stage_coordinator()
    assert any(name == "cognitive_cycle" for name, _ in rt.jobs)
