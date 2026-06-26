"""M12 — Builtin local models + the BaseModel contract + security boundary."""

from core.intelligence.base import (BaseModel, InferenceRequest, Model, ModelInfo,
                                    ModelStatus, TaskType)
from core.intelligence.builtin_models import (CodingModel, MathModel, MemoryModel,
                                              PlanningModel, ReasonerModel,
                                              ResearchModel, builtin_models)


def test_six_builtins():
    models = builtin_models()
    assert len(models) == 6
    assert all(isinstance(m, Model) for m in models)   # satisfy the protocol


def test_math_model():
    r = MathModel().infer(InferenceRequest(task=TaskType.MATH.value,
                                           prompt="compute 7 * 6", context={"expression": "7*6"}))
    assert r.ok and r.structured["value"] == 42 and r.confidence > 0.9


def test_math_extracts_expression():
    r = MathModel().infer(InferenceRequest(prompt="what is 2 + 2 please"))
    assert r.ok and r.structured["value"] == 4


def test_coding_model_debug():
    r = CodingModel().infer(InferenceRequest(context={"code": "try:\n  pass\nexcept:\n  pass"}))
    assert r.ok and any("except" in i for i in r.structured["issues"])


def test_coding_model_architecture():
    r = CodingModel().infer(InferenceRequest(context={"architecture": {"components": [1], "auth": False}}))
    assert r.ok and r.structured["findings"]


def test_research_model():
    r = ResearchModel().infer(InferenceRequest(
        prompt="Flask is a microframework. It routes URLs to functions. It uses Jinja templates."))
    assert r.ok and r.text


def test_planning_model():
    r = PlanningModel().infer(InferenceRequest(prompt="build a web app with auth and database"))
    assert r.ok and r.structured["plan"]


def test_reasoner_model():
    r = ReasonerModel().infer(InferenceRequest(prompt="why does code break"))
    assert r.ok and r.structured["steps"]


def test_memory_model():
    r = MemoryModel().infer(InferenceRequest(context={"memories": [{"content": "a"}, {"content": "b"}]}))
    assert r.ok and len(r.structured["items"]) == 2


def test_base_model_times_latency():
    m = MathModel()
    r = m.infer(InferenceRequest(context={"expression": "1+1"}))
    assert r.latency_ms >= 0 and r.tokens >= 0


def test_base_model_catches_failure():
    class Bad(BaseModel):
        def __init__(self): super().__init__(ModelInfo(name="bad"))
        def _run(self, request): raise ValueError("boom")
    r = Bad().infer(InferenceRequest())
    assert not r.ok and "boom" in r.error      # failure is data, not a crash


def test_model_lifecycle():
    m = MathModel()
    assert not m.loaded
    m.load(); assert m.loaded and m.info.status == ModelStatus.LOADED.value
    m.unload(); assert not m.loaded


def test_models_hold_no_services():
    """Security: a model has no reference to any store/service."""
    for m in builtin_models():
        for v in vars(m).values():
            assert not hasattr(v, "conn") and not hasattr(v, "remember_knowledge")
