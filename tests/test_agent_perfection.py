"""
M45 — agent perfection pass: pins for the defects fixed in every agent.

base: honest health (a brain whose last cycle failed is degraded) and lazy
service resolution (a brain built before its service registers must not stay
blind forever). runtime: degradation reported on CHANGE, recovery announced.
learning: only NEW experience reinforces (watermark, not tick rate).
executive: focus staleness decay + a truthful became-focus flag. tiers: the
whole store is bounded, not just the working tier. codex: the per-cycle cap
applies to new filings, not scanned issues. pipeline: segments processed on a
worker so the mic stays drained while FRIDAY thinks.
"""

from __future__ import annotations

import time

import pytest

from core.brains.base import CognitiveBrain, SituationReportBus
from core.brains.executive.brain import ExecutiveBrain
from core.brains.learning.brain import LearningBrain
from core.brains.memory.tiers import MemoryTier, TieredMemory
from core.brains.runtime.brain import RuntimeBrain


class _Services:
    """try_get-compatible container whose registry can grow after brains build."""

    def __init__(self, **svcs):
        self._svcs = dict(svcs)

    def register(self, name, svc):
        self._svcs[name] = svc

    def try_get(self, name):
        return self._svcs.get(name)


# ── base: honest health ───────────────────────────────────────────────────────

class _FaultyBrain(CognitiveBrain):
    name = "faulty"
    fail = True

    def observe(self):
        if self.fail:
            raise RuntimeError("sensor exploded")
        return None


def test_a_failing_brain_reports_degraded_not_ok():
    brain = _FaultyBrain()
    brain.tick()
    assert brain.health()["status"] == "degraded"
    brain.fail = False
    brain.tick()
    assert brain.health()["status"] == "ok"          # honest recovery too


# ── base: late-registered services are found ──────────────────────────────────

class _Audio:
    def recent_events(self, limit=10):
        return [{"sound": "alarm", "confidence": 0.9}]


def test_brains_are_not_blind_to_late_registered_services():
    from core.brains.audio.brain import AudioBrain
    services = _Services()                           # audio NOT registered yet
    brain = AudioBrain(services=services, report_bus=SituationReportBus())
    assert brain.tick() is None                      # nothing to hear yet
    services.register("audio", _Audio())             # service comes online later
    report = brain.tick()
    assert report is not None and "alarm" in report.summary


# ── runtime: change-detection + recovery ──────────────────────────────────────

class _Runtime:
    def recent(self, limit=50):
        return []


class _HealthServices(_Services):
    def __init__(self, degraded):
        super().__init__(runtime=_Runtime())
        self.degraded = degraded

    def health(self):
        svc = {n: {"status": "degraded"} for n in self.degraded}
        return {"status": "ok", "services": svc}


def test_runtime_brain_reports_change_not_spam():
    services = _HealthServices(degraded=["vision"])
    brain = RuntimeBrain(services=services)
    first = brain.tick()
    assert first is not None and "vision" in first.summary
    assert brain.tick() is None, "same degradation reported twice (spam)"
    services.degraded = []                           # recovery
    recovered = brain.tick()
    assert recovered is not None and "nominal again" in recovered.summary
    assert recovered.data["recovered"] is True


# ── learning: new experience only ─────────────────────────────────────────────

class _Learning:
    def __init__(self):
        self._samples = []
        self._clock = 0.0

    def record(self, kind, category):
        self._clock += 1.0               # strictly increasing, clock-resolution-proof
        self._samples.append({"kind": kind, "data": {"category": category},
                              "ts": self._clock})

    def samples(self, limit=50):
        return self._samples[-limit:][::-1]


def test_idle_ticks_do_not_inflate_reinforcement():
    learning = _Learning()
    for _ in range(2):
        learning.record("tracking", "person")
    brain = LearningBrain(services=_Services(learning=learning))
    brain.tick()
    baseline = brain._counter["tracking:person"]
    assert baseline == 2
    for _ in range(10):                              # idle ticks, no new samples
        brain.tick()
    assert brain._counter["tracking:person"] == baseline, \
        "reinforcement grew with tick rate, not experience"
    learning.record("tracking", "person")            # real new experience
    brain.tick()
    assert brain._counter["tracking:person"] == baseline + 1


# ── executive: truthful focus flag + staleness decay ──────────────────────────

def test_receive_reports_focus_truthfully():
    ex = ExecutiveBrain()
    first = ex.receive({"summary": "a", "priority": 0.5})
    assert first["focus"] is True                    # used to be always False
    second = ex.receive({"summary": "b", "priority": 0.1})
    assert second["focus"] is False


def test_stale_focus_yields_to_fresh_situations():
    ex = ExecutiveBrain(config={"focus_half_life_s": 0.01})
    ex.receive({"summary": "old emergency", "priority": 0.95})
    time.sleep(0.08)                                 # several half-lives pass
    result = ex.receive({"summary": "fresh ordinary situation", "priority": 0.4})
    assert result["focus"] is True, "yesterday's emergency held focus forever"
    assert ex.working_memory.focus()["summary"] == "fresh ordinary situation"


def test_malformed_priority_does_not_crash_the_executive():
    ex = ExecutiveBrain()
    result = ex.receive({"summary": "odd", "priority": "very high"})
    assert result["accepted"] is True and result["priority"] == 0.5


# ── tiers: the whole store is bounded ─────────────────────────────────────────

def test_total_capacity_evicts_weakest_but_never_core_or_confirmed():
    tiers = TieredMemory(working_capacity=1000, max_items=10)
    core = tiers.store("the owner is Satvik", importance=1.0, confidence=1.0,
                       user_confirmed=True)
    assert core.tier == MemoryTier.CORE
    for i in range(30):
        tiers.store(f"episodic fact {i}", importance=0.5, confidence=0.5)
    counts = tiers.counts()
    assert counts["total"] <= 10, "store grew past max_items (24/7 leak)"
    assert tiers.recall("Satvik"), "a core memory was evicted"
    assert tiers.metrics()["evictions"] > 0


# ── codex agent: the cap limits filings, not vision ───────────────────────────

def test_codex_files_new_issues_beyond_the_first_batch(tmp_path, monkeypatch):
    from core.agents import friday_codex_agent as codex
    monkeypatch.setattr(codex, "PROPOSALS_VAULT", tmp_path)

    def issues(n, start=0):
        return [{"kind": "improvement", "target": f"core/m{i}.py",
                 "title": f"issue {i}", "intent": "fix", "why": "w", "change": "c"}
                for i in range(start, start + n)]

    monkeypatch.setattr(codex, "self_check",
                        lambda: {"checked": 1, "ok": 1, "issues": issues(8),
                                 "at": "now"})
    first = codex.run_once()
    assert first["new_proposals"] == codex._MAX_TODO_PROPOSALS

    # next cycle: the same 8 known issues PLUS one genuinely new one at the end
    monkeypatch.setattr(codex, "self_check",
                        lambda: {"checked": 1, "ok": 1,
                                 "issues": issues(8) + issues(1, start=99),
                                 "at": "now"})
    second = codex.run_once()
    assert second["new_proposals"] >= 1, \
        "a new issue behind known ones was never proposed (agent went silent)"


# ── pipeline: segments processed off the frame loop ───────────────────────────

def test_async_segments_defer_to_the_worker_and_still_route():
    import numpy as np
    from core.audio.listener.events import AudioEvent
    from core.audio.listener.microphone import ArraySource, silence, tone
    from core.audio.listener.pipeline import ListeningPipeline
    from core.audio.listener.transcription import FakeTranscriber
    from tests.test_audio_pipeline import FakeIOS

    wav = np.concatenate([silence(0.2), tone(0.5, 300, 0.3), silence(1.0)])
    ios = FakeIOS()
    p = ListeningPipeline(microphone=ArraySource(wav),
                          transcriber=FakeTranscriber(script=["friday hello"]),
                          intelligence_os=ios, async_segments=True)
    finished = []
    p.bus.on_any(lambda e: finished.append(e.kind)
                 if e.kind == AudioEvent.COMMAND_FINISHED.value else None)
    p.start()                                        # worker + frame loop
    deadline = time.time() + 5.0
    while not finished and time.time() < deadline:
        time.sleep(0.02)
    p.stop()
    assert finished, "segment never processed by the worker"
    assert ios.calls and ios.calls[0][0] == "hello"

    # and the synchronous default is unchanged for direct drivers
    p2 = ListeningPipeline(microphone=ArraySource(wav),
                           transcriber=FakeTranscriber(script=["friday hello"]),
                           intelligence_os=FakeIOS())
    assert p2.pump() > 0
