"""M13 — Self Model: aggregation from injected providers, graceful degradation."""

from core.cognition_core.self_model import SelfModel


class _Sensors:
    def list(self): return ["system_sensor", "time_sensor"]


class _Coord:
    def active_workers(self): return [{"id": "w1"}, {"id": "w2"}]


class _Society:
    coordinator = _Coord()


class _Resources:
    def system(self): return {"available": True, "cpu_percent": 12, "ram_percent": 40,
                              "gpu": {"present": False}}


class _Exploding:
    def __getattr__(self, name):
        def boom(*a, **k): raise RuntimeError("provider down")
        return boom


def test_empty_self_model():
    snap = SelfModel().snapshot()
    assert snap.active_goals == [] and snap.active_agents == 0
    assert "cpu-only" in snap.limitations


def test_aggregates_providers():
    sm = SelfModel(sensor_registry=_Sensors(), society=_Society(),
                   resource_monitor=_Resources(),
                   cognitive_state={"current_task": "ship M13", "active_plan": "PLAN_1"})
    snap = sm.snapshot()
    assert snap.sensors == ["system_sensor", "time_sensor"]
    assert snap.active_agents == 2
    assert snap.current_task == "ship M13" and snap.current_plan == "PLAN_1"
    assert snap.compute["available"] and snap.compute["cpu_percent"] == 12
    assert "no-gpu" in snap.limitations          # derived from compute.gpu.present == False
    assert snap.workload["active_agents"] == 2


def test_active_goals_from_goal_service(goal_service):
    g = goal_service.create_goal("Ship M13", priority=1)
    goal_service.activate_goal(g.goal_id)
    snap = SelfModel(goal_service=goal_service).snapshot()
    assert "Ship M13" in snap.active_goals


def test_graceful_when_provider_explodes():
    sm = SelfModel(sensor_registry=_Exploding(), society=_Exploding(),
                   resource_monitor=_Exploding(), goal_service=_Exploding())
    snap = sm.snapshot()                          # must not raise
    assert snap.sensors == [] and snap.active_agents == 0
    assert snap.compute == {"available": False}


def test_confidence_drops_under_memory_pressure():
    class HighRam:
        def system(self): return {"available": True, "ram_percent": 95}
    snap = SelfModel(resource_monitor=HighRam()).snapshot()
    assert snap.confidence < 0.9


def test_serializable():
    import json
    json.dumps(SelfModel().snapshot().to_dict())
