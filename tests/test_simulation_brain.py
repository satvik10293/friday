"""M19 — Simulation Brain units + pipeline: forecast, prediction, risk, scenario
generation, decision evaluation, comparison, and the simulate() orchestration (ranking,
rejection, events, never-raises, config, incremental timeout). Distinct from the M11
core/simulation tests."""

import importlib

import pytest

from core.brains.simulation.comparison import PlanComparison
from core.brains.simulation.config import SimulationConfig
from core.brains.simulation.decision_evaluator import DecisionEvaluator
from core.brains.simulation.events import SimulationEvent
from core.brains.simulation.forecast import ForecastEngine
from core.brains.simulation.interfaces import Scenario, SimulationRequest
from core.brains.simulation.predictor import PredictionEngine
from core.brains.simulation.risk_engine import RiskEngine
from core.brains.simulation.scenario_generator import ScenarioGenerator
from core.brains.simulation.simulation import SimulationBrain


def _req(action, **kw):
    return SimulationRequest(action=action, **kw)


# ── forecast engine ──────────────────────────────────────────────────────────────────
def test_forecast_action_signatures():
    f = ForecastEngine()
    dl = f.forecast(Scenario("direct", ["download"]), _req("download the dataset"))
    assert dl.network >= 0.5 and dl.duration_s > 0
    bk = f.forecast(Scenario("backup_then", ["back up", "delete"], tags=["backup"]),
                    _req("delete the folder"))
    assert bk.storage_mb >= 200 and 0 <= bk.system_load <= 1


# ── prediction engine ────────────────────────────────────────────────────────────────
def test_prediction_safe_vs_risky():
    p = PredictionEngine()
    risky = p.predict(Scenario("immediate", ["delete"], tags=["destructive"]),
                      _req("delete the folder"))
    safe = p.predict(Scenario("ask_user", ["ask", "delete"], tags=["destructive", "ask_user"]),
                     _req("delete the folder"))
    assert safe.success_probability > risky.success_probability
    assert "irreversible data loss" in risky.failure_modes
    assert risky.intent == "remove data"


def test_prediction_accuracy_prior_adjusts():
    p = PredictionEngine()
    p.set_accuracy_prior(0.95)
    c = p.predict(Scenario("direct", ["open"]), _req("open the file"))
    assert c.confidence > 0.7


# ── risk engine ──────────────────────────────────────────────────────────────────────
def test_risk_destructive_high_unless_mitigated():
    r = RiskEngine()
    pr = PredictionEngine().predict(Scenario("immediate", ["delete"], tags=["destructive"]),
                                    _req("delete the folder"))
    fc = ForecastEngine().forecast(Scenario("immediate", ["delete"]), _req("delete the folder"))
    risky = r.assess(Scenario("immediate", ["delete"], tags=["destructive"]), pr, fc,
                     _req("delete the folder"))
    safe = r.assess(Scenario("ask_user", ["ask", "delete"], tags=["destructive", "ask_user"]),
                    pr, fc, _req("delete the folder"))
    assert risky.safety > safe.safety
    assert 0.0 <= risky.overall <= 1.0 and risky.reasons


def test_risk_sensitive_action_privacy_security():
    r = RiskEngine()
    sc = Scenario("direct", ["send"], tags=["external"])
    pr = PredictionEngine().predict(sc, _req("send the report"))
    fc = ForecastEngine().forecast(sc, _req("send the report"))
    risk = r.assess(sc, pr, fc, _req("send the report"))
    assert risk.privacy > 0 and risk.security > 0


# ── scenario generator ───────────────────────────────────────────────────────────────
def test_scenarios_for_destructive_action():
    names = {s.name for s in ScenarioGenerator().generate(_req("delete the folder"))}
    assert {"immediate", "backup_then", "ask_user"} <= names


def test_scenarios_external_and_generic():
    ext = {s.name for s in ScenarioGenerator().generate(_req("share the document"))}
    assert "ask_user" in ext
    gen = {s.name for s in ScenarioGenerator().generate(_req("compute statistics"))}
    assert {"direct", "cautious", "deferred"} <= gen


def test_scenarios_explicit_options_and_cap():
    sg = ScenarioGenerator()
    opt = sg.generate(_req("x", options=["a", "b"]))
    assert [s.name for s in opt] == ["a", "b"]
    assert len(sg.generate(_req("delete the folder"), max_scenarios=2)) == 2


def test_scenario_generator_custom_plugin():
    sg = ScenarioGenerator()
    sg.register(lambda r: r.action == "special",
                lambda r: [Scenario("custom", ["x"], tags=["plugin"])])
    assert sg.generate(_req("special"))[0].name == "custom"


# ── decision evaluator + comparison ──────────────────────────────────────────────────
def test_evaluator_policy_gate_and_ranking():
    cfg = SimulationConfig.from_dict({})
    ev = DecisionEvaluator(cfg)
    req = _req("delete the folder")
    p, f, r = PredictionEngine(), ForecastEngine(), RiskEngine()
    evals = []
    for sc in ScenarioGenerator().generate(req):
        pr = p.predict(sc, req); fc = f.forecast(sc, req); rk = r.assess(sc, pr, fc, req)
        evals.append(ev.evaluate(sc, pr, fc, rk, req))
    ranked = PlanComparison.rank(evals)
    # the unmitigated 'immediate' plan is policy-non-compliant and ranks last
    assert ranked[-1].scenario.name == "immediate" and not ranked[-1].policy_compliant
    assert ranked[0].policy_compliant
    summary = PlanComparison.summarize(ranked)
    assert summary["best"] == ranked[0].scenario.name


# ── brain pipeline ───────────────────────────────────────────────────────────────────
class FakeRuntime:
    def __init__(self): self.events = []
    def emit(self, sig, data=None, source=None): self.events.append(getattr(sig, "value", sig))
    def register_health(self, n, p): pass


def _brain(**cfg):
    from core.services import build_default_container, ServiceName
    rt = FakeRuntime()
    c = build_default_container(runtime=rt)
    b = SimulationBrain(services=c, config=SimulationConfig.from_dict(cfg).to_dict())
    return b, rt


def test_simulate_ranks_and_recommends_safest():
    b, rt = _brain(risk_threshold=0.7)
    res = b.simulate("delete the project folder")
    assert not res["rejected"]
    assert res["recommended"]["scenario"]["name"] in ("ask_user", "backup_then", "dry_run")
    kinds = set(rt.events)
    for e in (SimulationEvent.SIMULATION_REQUESTED, SimulationEvent.PREDICTION_GENERATED,
              SimulationEvent.RISK_CALCULATED, SimulationEvent.PLAN_RANKED,
              SimulationEvent.SIMULATION_COMPLETED):
        assert e.value in kinds


def test_simulate_rejects_when_threshold_strict():
    b, rt = _brain(risk_threshold=0.05)        # even safe plans exceed this
    res = b.simulate("delete the project folder")
    assert res["rejected"] and SimulationEvent.SIMULATION_REJECTED.value in set(rt.events)


def test_simulate_disabled_is_noop():
    b, _ = _brain(enabled=False)
    assert b.simulate("anything") == {"enabled": False}


def test_simulate_never_raises():
    b, _ = _brain()
    b.scenarios.generate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    res = b.simulate("delete the folder")
    assert res["rejected"] and "error" in res        # absorbed, advisory failure


def test_incremental_timeout_budget():
    b, _ = _brain(timeout_seconds=0.0)               # zero budget → stops after first scenario
    res = b.simulate("delete the project folder")
    assert len(res["ranked_plans"]) >= 1


def test_forecast_api():
    b, _ = _brain()
    fc = b.forecast("download the dataset")
    assert fc["network"] >= 0.5 and "duration_s" in fc


def test_side_effect_free_import_and_no_circular():
    import ast, pathlib
    importlib.import_module("core.brains.simulation")
    # services/base must not import the simulation brain (one-way)
    for pkg in ("core/services", "core/brains/base.py"):
        root = pathlib.Path(pkg)
        files = [root] if root.is_file() else list(root.rglob("*.py"))
        for f in files:
            for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert "brains.simulation" not in node.module
