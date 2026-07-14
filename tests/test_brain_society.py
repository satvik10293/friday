"""
M46 — a brain for every module: knowledge, goals, voice, reasoning.

Each new brain follows the standard lifecycle, observes ONLY through its
service, reports on CHANGE (steady state stays silent — the M45 lesson), and
recovers from late service registration (never permanently blind). All four
join _LIFECYCLE_BRAINS, so the Coordinator ticks them and their reports reach
the main brain (the Executive) like every other member of the society.
"""

from __future__ import annotations

from core.brains import build_brains
from core.brains.base import SituationReportBus
from core.brains.goals.brain import GoalBrain
from core.brains.knowledge.brain import KnowledgeBrain
from core.brains.reasoning.brain import ReasoningBrain
from core.brains.voice.brain import VoiceBrain
from tests.test_agent_perfection import _Services


# ── fakes ─────────────────────────────────────────────────────────────────────

class _Knowledge:
    def __init__(self, active=5):
        self.active = active

    def stats(self):
        return {"total": self.active + 2, "active": self.active, "archived": 2}


class _Goals:
    def __init__(self, proposals=(), active=0):
        self.proposals = list(proposals)
        self.active = active

    def status(self):
        return {"counts": {"active": self.active, "pending": 1},
                "proposals": list(self.proposals)}


class _Conversation:
    def __init__(self):
        self.turns = 0
        self.reasoner = {"available": True, "model": "gpt-oss-test",
                         "failed": 0, "fallbacks": 0, "avg_latency_ms": 1100.0}

    def status(self):
        return {"turns": self.turns, "cloud_turns": self.turns,
                "clarifications": 0, "echoes_dropped": 0,
                "reasoner": dict(self.reasoner)}


class _IOS:
    def __init__(self, models=6):
        self.models = models

    def health_report(self):
        return {"status": "ok", "models_loaded": self.models}


# ── knowledge brain ───────────────────────────────────────────────────────────

def test_knowledge_brain_reports_growth_then_stays_quiet():
    svc = _Knowledge(active=5)
    brain = KnowledgeBrain(services=_Services(knowledge=svc))
    first = brain.tick()
    assert first is not None and "5 note(s)" in first.summary
    assert brain.tick() is None                      # no growth → silence
    svc.active = 8
    grown = brain.tick()
    assert grown is not None and "(+3)" in grown.summary
    assert grown.data["delta"] == 3


def test_knowledge_brain_recovers_from_late_registration():
    services = _Services()
    brain = KnowledgeBrain(services=services)
    assert brain.tick() is None
    services.register("knowledge", _Knowledge(active=3))
    report = brain.tick()
    assert report is not None and "3 note(s)" in report.summary


# ── goal brain ────────────────────────────────────────────────────────────────

def test_goal_brain_surfaces_proposals_and_recommends_review():
    svc = _Goals(proposals=["tidy the vault", "index PDFs"], active=1)
    brain = GoalBrain(services=_Services(goals=svc))
    report = brain.tick()
    assert report is not None
    assert "2 proposal(s) await approval" in report.summary
    assert report.recommended_action == "review_proposals"
    assert brain.tick() is None                      # unchanged → silence
    svc.proposals = []                               # proposals resolved
    cleared = brain.tick()
    assert cleared is not None and "no proposals waiting" in cleared.summary
    assert cleared.recommended_action is None


# ── voice brain ───────────────────────────────────────────────────────────────

def test_voice_brain_reports_new_turns_only():
    svc = _Conversation()
    brain = VoiceBrain(services=_Services(conversation=svc))
    assert brain.tick() is None                      # zero turns → silence
    svc.turns = 3
    report = brain.tick()
    assert report is not None and "3 turn(s)" in report.summary
    assert brain.tick() is None                      # same count → silence


# ── reasoning brain ───────────────────────────────────────────────────────────

def test_reasoning_brain_reports_health_and_flags_degradation():
    conv = _Conversation()
    brain = ReasoningBrain(services=_Services(intelligence=_IOS(models=6),
                                              conversation=conv))
    first = brain.tick()
    assert first is not None and "6 local model(s)" in first.summary
    assert "healthy" in first.summary and first.priority < 0.5
    assert brain.tick() is None                      # steady state → silence
    conv.reasoner["failed"] = 2                      # cloud starts failing
    degraded = brain.tick()
    assert degraded is not None and degraded.priority >= 0.7
    assert degraded.recommended_action == "check_cloud_reasoner"
    assert degraded.data["degraded"] is True


# ── the society ───────────────────────────────────────────────────────────────

def test_build_brains_includes_one_brain_per_module():
    brains = build_brains(services=_Services(), report_bus=SituationReportBus())
    for name in ("vision_brain", "audio_brain", "spatial_brain", "learning_brain",
                 "emotion_brain", "automation_brain", "runtime_brain",
                 "knowledge_brain", "goal_brain", "voice_brain",
                 "reasoning_brain", "memory_brain"):
        assert name in brains, f"{name} missing from the society"
    assert len(brains) == 12
