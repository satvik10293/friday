"""M19 — Simulation integration: Executive Brain think-before-acting (deliberate),
learning feedback (record_outcome), meaningful-only memory persistence, and the
SimulationService facade. The Executive stays in charge; the Memory Brain is not bypassed."""

import pytest

from core.brains.executive.brain import ExecutiveBrain
from core.brains.simulation import SimulationConfig, SimulationService
from core.services import ServiceName, build_default_container


class FakeRuntime:
    def __init__(self): self.events = []
    def emit(self, sig, data=None, source=None): self.events.append(getattr(sig, "value", sig))
    def register_health(self, n, p): pass


class MemBrain:
    name = "memory_brain"
    def __init__(self): self.remembered = []
    def remember(self, content, *, importance=0.4, confidence=0.5, kind="event", **k):
        self.remembered.append((kind, content))
    def recall(self, q, *, limit=5): return []


class LearningSvc:
    name = "learning"
    def __init__(self): self.records = []
    def record(self, kind, data): self.records.append((kind, data))
    def samples(self, *, kind="", limit=100): return []
    def health(self): return {"status": "placeholder"}


def _stack(**cfg):
    rt = FakeRuntime()
    mem = MemBrain()
    learn = LearningSvc()
    container = build_default_container(runtime=rt)
    container.register("memory_brain", mem)
    container.register(ServiceName.LEARNING, learn)
    sim = SimulationService(SimulationConfig.from_dict(cfg), container=container)
    ex = ExecutiveBrain(services=container)
    return ex, sim, mem, learn, container


# ── Executive deliberation (think-before-acting) ─────────────────────────────────────
def test_executive_deliberates_via_simulation():
    ex, sim, _, _, _ = _stack(risk_threshold=0.7)
    decision = ex.deliberate("delete the project folder")
    assert decision["simulated"] is True
    assert decision["chosen_plan"] in ("ask_user", "backup_then", "dry_run")
    # coherence: if the winning plan is "confirm with the user first", the
    # DECISION is ask_user — never "execute the plan that says to ask"
    if decision["chosen_plan"] == "ask_user":
        assert decision["decision"] == "ask_user"
    else:
        assert decision["decision"] == "execute"
    assert "simulation_id" in decision and ex.metrics()["deliberations"] == 1


def test_executive_asks_user_when_all_plans_rejected():
    ex, sim, _, _, _ = _stack(risk_threshold=0.05)
    decision = ex.deliberate("delete the project folder")
    assert decision["decision"] == "ask_user" and decision["simulated"] is True


def test_executive_fallback_without_simulation_service():
    ex = ExecutiveBrain(services=build_default_container())   # no simulation registered
    decision = ex.deliberate("delete the folder")
    assert decision["simulated"] is False and decision["decision"] == "execute"


def test_executive_survives_simulation_error():
    ex, sim, _, _, container = _stack()
    sim.simulate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("sim down"))
    decision = ex.deliberate("delete the folder")
    assert decision["simulated"] is False              # error absorbed; Executive proceeds


# ── learning feedback ────────────────────────────────────────────────────────────────
def test_report_outcome_learning_feedback():
    ex, sim, _, learn, _ = _stack()
    decision = ex.deliberate("delete the project folder")
    fb = ex.report_outcome(decision["simulation_id"], {"success": True})
    assert fb["error"] is not None and 0.0 <= fb["error"] <= 1.0
    assert learn.records and learn.records[0][0] == "prediction_outcome"


def test_repeated_failures_remembered():
    ex, sim, mem, _, _ = _stack()
    for _ in range(3):
        d = ex.deliberate("send the report")
        ex.report_outcome(d["simulation_id"], {"success": False})
    assert any("Repeated failures" in c for _, c in mem.remembered)


def test_record_outcome_unknown_simulation():
    _, sim, _, _, _ = _stack()
    assert sim.record_outcome("SIM_nope", {"success": True})["error"] is None


# ── meaningful-only memory persistence (Memory Brain not bypassed) ───────────────────
def test_meaningful_simulations_persisted_via_memory_brain():
    ex, sim, mem, _, _ = _stack(risk_threshold=0.7)
    sim.simulate("delete the project folder")          # high-success safe plan → meaningful
    assert mem.remembered and mem.remembered[0][0] == "simulation"


def test_temporary_simulations_not_flooded():
    ex, sim, mem, _, _ = _stack(store_successful_simulations=False)
    sim.simulate("open the file")
    assert not mem.remembered                           # storage disabled → nothing persisted


# ── service facade ───────────────────────────────────────────────────────────────────
def test_service_registers_and_exposes_api():
    ex, sim, _, _, container = _stack()
    assert container.get(ServiceName.SIMULATION) is sim
    assert "duration_s" in sim.forecast("download the dataset")
    d = sim.dashboard()
    assert d["title"] == "Simulation Brain" and d["metrics"]["simulations"] >= 0
    m = sim.manifest()
    assert m["subsystem"] == "simulation_brain" and m["milestone"] == "M19"
    assert sim.health()["status"] == "ok"


def test_simulation_brain_never_executes():
    # the simulate result is advisory data only — no side effect beyond memory/events
    ex, sim, mem, _, _ = _stack()
    res = sim.simulate("format the disk")
    assert "ranked_plans" in res and "recommended" in res   # advice, not execution
