"""M17-rev — Cognitive Coordinator: merge, dedup, conflict resolution, context, the
Executive gateway, events, society cycle, graceful degradation, no circular imports."""

import ast
import importlib
import pathlib

import pytest

from core.brains.base import SituationReport, SituationReportBus
from core.coordinator import CognitiveCoordinator, CoordinatorConfig, CoordinatorService
from core.coordinator.events import CoordinatorEvent
from core.services import ServiceName, build_default_container


class FakeRuntime:
    def __init__(self): self.events = []
    def emit(self, sig, data=None, source=None): self.events.append(getattr(sig, "value", sig))
    def register_health(self, n, p): pass


class FakeExec:
    def __init__(self): self.received = []
    def receive(self, situation): self.received.append(situation); return {"accepted": True}


def _coord(**over):
    cfg = {"min_priority_to_executive": 0.0, "dedup_window_s": 5.0}
    cfg.update(over)
    container = build_default_container(runtime=FakeRuntime())
    ex = FakeExec()
    container.register("executive_brain", ex)
    bus = SituationReportBus()
    co = CognitiveCoordinator(CoordinatorConfig.from_dict(cfg), services=container, report_bus=bus)
    return co, ex, container, bus


def _r(brain, summary, *, conf=0.8, prio=0.5, cat="status", **data):
    return SituationReport(source_brain=brain, summary=summary, confidence=conf,
                           priority=prio, category=cat, data=data)


# ── merge ────────────────────────────────────────────────────────────────────────────
def test_merges_reports_from_multiple_brains():
    co, ex, _, _ = _coord()
    co.submit(_r("vision_brain", "I see a laptop", prio=0.4))
    co.submit(_r("audio_brain", "I hear typing", prio=0.45))
    out = co.coordinate()
    assert len(out) == 1
    u = out[0]
    assert set(u["source_brains"]) == {"vision_brain", "audio_brain"}
    assert ex.received and ex.received[0]["id"] == u["id"]    # published to Executive


def test_emergency_is_its_own_situation_and_immediate():
    co, ex, _, _ = _coord()
    co.submit(_r("audio_brain", "Glass breaking!", conf=0.95, prio=1.0, cat="emergency"))
    # emergency coordinates immediately on submit (no explicit coordinate() needed)
    assert ex.received and ex.received[0]["category"] == "emergency"


# ── dedup ────────────────────────────────────────────────────────────────────────────
def test_removes_duplicate_situations():
    co, ex, container, _ = _coord(dedup_similarity=0.9)
    rt = container.get(ServiceName.RUNTIME)._runtime
    co.submit(_r("vision_brain", "I see a cat", prio=0.5, cat="vision"))
    co.coordinate()
    co.submit(_r("vision_brain", "I see a cat", prio=0.5, cat="vision"))
    co.coordinate()
    assert co.metrics()["duplicates"] == 1
    assert CoordinatorEvent.DUPLICATE_REMOVED.value in set(rt.events)
    assert len(ex.received) == 1                        # the duplicate was not re-published


def test_conflict_resolution_recorded():
    co, ex, _, _ = _coord()
    co.submit(_r("spatial_brain", "user present", prio=0.5, cat="spatial", user_state="present"))
    co.submit(_r("runtime_brain", "user gone", prio=0.5, cat="runtime", user_state="unavailable"))
    out = co.coordinate()
    assert out[0]["conflicts"]                          # conflict detected + recorded


# ── context + gateway ────────────────────────────────────────────────────────────────
def test_maintains_context_and_is_only_executive_gateway():
    co, ex, _, _ = _coord()
    co.submit(_r("spatial_brain", "user working in office", prio=0.6, cat="spatial",
                room="office", user_state="working"))
    co.coordinate()
    assert co.context()["room"] == "office" and co.context()["activity"] == "working"
    assert len(ex.received) == 1                        # exactly one publish path


def test_priority_gate_to_executive():
    co, ex, _, _ = _coord(min_priority_to_executive=0.8)
    co.submit(_r("vision_brain", "trivial", prio=0.2))
    co.coordinate()
    assert not ex.received                              # below gate → not sent to Executive


def test_events_published():
    co, ex, container, _ = _coord()
    rt = container.get(ServiceName.RUNTIME)._runtime
    co.submit(_r("vision_brain", "I see a laptop", prio=0.4))
    co.submit(_r("audio_brain", "I hear typing", prio=0.45))
    co.coordinate()
    kinds = set(rt.events)
    assert CoordinatorEvent.SITUATION_BUILT.value in kinds
    assert CoordinatorEvent.PUBLISHED_TO_EXECUTIVE.value in kinds
    assert CoordinatorEvent.REPORTS_MERGED.value in kinds


def test_coordinate_never_raises_when_empty():
    co, _, _, _ = _coord()
    assert co.coordinate() == []


# ── full society cycle + graceful degradation ───────────────────────────────────────
def test_society_cycle_via_service():
    from core.services.vision_service import VisionService
    container = build_default_container(runtime=FakeRuntime())
    container.register(ServiceName.VISION, VisionService(provider=lambda: [
        {"object_class": "laptop", "label": "laptop", "confidence": 0.9}]))
    svc = CoordinatorService(CoordinatorConfig.from_dict({"min_priority_to_executive": 0.0}),
                             container=container)
    res = svc.cycle()
    assert res["reports"] >= 1 and isinstance(res["situations"], list)
    assert svc.health()["status"] in ("ok", "degraded")
    svc.close()


def test_graceful_degradation_one_brain_fails():
    from core.brains.vision.brain import VisionBrain
    container = build_default_container(runtime=FakeRuntime())

    class BadVision:
        name = "vision"
        def detect(self): raise RuntimeError("camera dead")
        def cameras(self): return []
        def health(self): return {"status": "error"}
    container.register(ServiceName.VISION, BadVision())
    svc = CoordinatorService(CoordinatorConfig.from_dict({}), container=container)
    res = svc.cycle()                                   # vision brain fails, others continue
    assert "situations" in res                          # cycle completed despite the failure
    assert svc.brains["vision_brain"].metrics()["errors"] >= 1
    svc.close()


def test_no_circular_import():
    # brains/coordinator depend on services + hub; those must NOT import brains/coordinator
    for pkg in ("core/services", "core/perception/hub"):
        imports = set()
        for p in pathlib.Path(pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
        assert not [m for m in imports if m and ("core.brains" in m or "core.coordinator" in m)]


def test_manifest_and_dashboard():
    svc = CoordinatorService(CoordinatorConfig.from_dict({}), container=build_default_container())
    m = svc.manifest()
    assert m["subsystem"] == "cognitive_coordinator"
    assert svc.dashboard()["title"] == "Cognitive Coordinator"
    svc.close()
