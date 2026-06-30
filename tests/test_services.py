"""M16 — Service layer: DI container, graceful wrappers, decoupled event bus, world-model
fallback, configuration, plugins, placeholders, mockability, side-effect-free import."""

import importlib

import pytest

from core.services import (ServiceContainer, ServiceName, build_default_container,
                           ConfigurationService, PluginService, RuntimeService,
                           WorldModelService, MemoryService, AttentionService)


# ── DI container ───────────────────────────────────────────────────────────────────
def test_container_register_and_resolve():
    c = ServiceContainer()
    c.register("x", object())
    assert c.has("x") and c.get("x") is c.get("x")
    with pytest.raises(KeyError):
        c.get("missing")
    assert c.try_get("missing") is None


def test_container_lazy_factory_built_once():
    c = ServiceContainer()
    calls = []
    c.register_factory("y", lambda _c: calls.append(1) or object())
    a, b = c.get("y"), c.get("y")
    assert a is b and len(calls) == 1


def test_default_container_wires_all_services():
    c = build_default_container()
    for name in ServiceName.ALL:
        if name in ("spatial", "perception"):
            continue                                   # these register themselves
        assert c.has(name), name
    assert c.health()["status"] == "ok"


# ── runtime event bus (decoupled) ──────────────────────────────────────────────────
def test_runtime_service_local_bus():
    rt = RuntimeService()
    seen = []
    rt.subscribe("E", lambda ev: seen.append(ev["data"]))
    rt.publish("E", {"n": 1})
    assert seen == [{"n": 1}]
    assert rt.recent()[0]["event"] == "E"


def test_runtime_service_forwards_to_runtime():
    forwarded = []

    class FakeRuntime:
        def emit(self, sig, data=None, source=None):
            forwarded.append((getattr(sig, "value", sig), source))

    rt = RuntimeService(FakeRuntime())
    rt.publish("E", {"n": 2}, source="spatial")
    assert forwarded == [("E", "spatial")]


def test_runtime_subscriber_failure_isolated():
    rt = RuntimeService()
    rt.subscribe("E", lambda ev: 1 / 0)               # bad subscriber
    rt.publish("E", {})                                # must not raise
    assert rt.health()["published"] == 1


# ── world model service (fallback) ─────────────────────────────────────────────────
def test_world_model_service_fallback():
    wm = WorldModelService(None)
    eid = wm.observe("object", "phone", state={"room": "office"})
    assert wm.get(eid)["state"]["room"] == "office"
    assert wm.health()["backend"] == "in_memory_fallback"


def test_world_model_service_adapts_real_world_model(tmp_path):
    from core.world.world_model import WorldModel
    wm = WorldModel(path=str(tmp_path / "w.db"))
    svc = WorldModelService(wm)
    eid = svc.observe("object", "laptop", state={"room": "office"})
    assert eid and svc.get(eid)["name"] == "laptop"
    wm.close()


# ── memory / attention / config / plugin ───────────────────────────────────────────
def test_memory_service_local_recall():
    m = MemoryService(None)
    m.remember("phone moved to the office", kind="spatial")
    assert m.recall("phone") and "phone" in m.recall("phone")[0]["content"]


def test_attention_service_fallback_sort():
    a = AttentionService(None)
    ranked = a.rank([{"importance": 0.2, "id": "a"}, {"importance": 0.9, "id": "b"}])
    assert ranked[0]["id"] == "b"


def test_configuration_service_dotted_path():
    cfg = ConfigurationService({"spatial": {"confidence_threshold": 0.7, "nested": {"k": 1}}})
    assert cfg.get("spatial.confidence_threshold") == 0.7
    assert cfg.get("spatial.nested.k") == 1
    assert cfg.get("missing.path", "d") == "d"
    assert cfg.section("spatial")["confidence_threshold"] == 0.7
    cfg.set("spatial.new", 5)
    assert cfg.get("spatial.new") == 5


def test_plugin_service_registry():
    p = PluginService()
    p.register("camera", "usb", lambda: "usb-cam")
    assert "usb" in p.list("camera")
    assert p.get("camera", "usb")() == "usb-cam"
    assert p.get("camera", "missing") is None


def test_placeholders_report_placeholder_status():
    c = build_default_container()
    assert c.get(ServiceName.LEARNING).health()["status"] == "placeholder"
    assert c.get(ServiceName.EMOTION).health()["status"] == "placeholder"


def test_services_are_mockable():
    # any object structurally satisfying a protocol can be injected (duck typing)
    class MockWorld:
        name = "world_model"
        def observe(self, *a, **k): return "ENT_mock"
        def relate(self, *a, **k): pass
        def get(self, e): return {"entity_id": e}
        def health(self): return {"status": "ok"}
    c = ServiceContainer()
    c.register(ServiceName.WORLD_MODEL, MockWorld())
    assert c.get(ServiceName.WORLD_MODEL).observe("object", "x") == "ENT_mock"


def test_side_effect_free_import():
    importlib.import_module("core.services")
    for m in ("runtime_service", "world_model_service", "memory_service", "vision_service",
              "audio_service", "container", "interfaces"):
        importlib.import_module(f"core.services.{m}")
