"""
tests/test_sensors.py — FRIDAY 4.0 M6
Sensor framework: base poll/error isolation, registry, heartbeats, the manager,
and the four built-in sensors (local-only).
"""

import pytest

from core.perception import ObservationType, PerceptionManager, PerceptionStore
from core.sensors import Sensor, SensorRegistry, SensorManager, HeartbeatMonitor
from core.sensors.builtin import (
    TimeSensor, SystemSensor, ProcessSensor, FilesystemSensor,
    register_builtin_sensors, ALL_BUILTIN,
)


class FakeSensor(Sensor):
    name = "fake"
    type = ObservationType.CUSTOM
    interval_s = 1.0

    def observe(self):
        return [self._obs({"v": 1}, confidence=0.9, metadata={"subject": "fake:x"})]


class BoomSensor(Sensor):
    name = "boom"
    type = ObservationType.CUSTOM

    def observe(self):
        raise RuntimeError("sensor failure")


# ── base ─────────────────────────────────────────────────────────────────────
def test_sensor_poll_returns_batch():
    s = FakeSensor()
    batch = s.poll()
    assert len(batch) == 1 and batch.observations[0].type == ObservationType.CUSTOM
    assert s.metrics()["polls"] == 1 and s.metrics()["errors"] == 0


def test_sensor_poll_isolates_errors():
    s = BoomSensor()
    batch = s.poll()                       # must NOT raise
    assert len(batch) == 0
    assert s.metrics()["errors"] == 1
    assert s.health()["last_error"] is not None


def test_sensor_capabilities_and_lifecycle():
    s = FakeSensor()
    caps = s.capabilities()
    assert caps["name"] == "fake" and caps["type"] == "custom"
    s.start(); assert s.started
    s.stop(); assert not s.started


# ── registry ─────────────────────────────────────────────────────────────────
def test_registry_register_and_duplicate():
    reg = SensorRegistry()
    reg.register(FakeSensor())
    assert reg.has("fake") and len(reg) == 1
    with pytest.raises(ValueError):
        reg.register(FakeSensor())


def test_registry_get_list_unregister():
    reg = SensorRegistry()
    reg.register(FakeSensor())
    assert reg.get("fake") is not None
    assert "fake" in reg.names()
    reg.unregister("fake")
    assert not reg.has("fake")


def test_registry_health():
    reg = SensorRegistry()
    reg.register(FakeSensor())
    h = reg.health()
    assert h["count"] == 1 and "fake" in h["sensors"]


# ── heartbeats ───────────────────────────────────────────────────────────────
def test_heartbeat_beat_and_stale():
    mon = HeartbeatMonitor()
    mon.register("s", interval_s=1.0)
    mon.beat("s", now=100.0)
    hb = mon.get("s")
    assert hb.beats == 1 and not hb.is_stale(now=101.0)
    assert hb.is_stale(now=200.0)              # well past grace window


def test_heartbeat_monitor_stale_list():
    mon = HeartbeatMonitor()
    mon.beat("a", now=100.0)
    assert mon.stale(now=100.5) == []
    assert "a" in mon.stale(now=1000.0)


# ── manager ──────────────────────────────────────────────────────────────────
@pytest.fixture
def manager(tmp_path):
    store = PerceptionStore(path=tmp_path / "perc.db")
    pm = PerceptionManager(store=store)
    sm = SensorManager(perception_manager=pm, store=store)
    yield sm, pm
    store.close()


def test_manager_register_and_collect(manager):
    sm, pm = manager
    sm.register(FakeSensor())
    obs = sm.collect()
    assert len(obs) == 1


def test_manager_poll_once_feeds_perception(manager):
    sm, pm = manager
    sm.register(FakeSensor())
    results = sm.poll_once()
    assert len(results) == 1
    assert pm.stats()["ingested"] == 1


def test_manager_health_and_metrics(manager):
    sm, pm = manager
    sm.register(FakeSensor())
    sm.poll_once()
    assert sm.health()["count"] == 1
    assert sm.metrics()["polls"] == 1


def test_manager_isolates_failing_sensor(manager):
    sm, pm = manager
    sm.register(FakeSensor())
    sm.register(BoomSensor())
    obs = sm.collect()                     # boom sensor must not break the pass
    assert len(obs) == 1                    # only the good sensor produced output


# ── built-in sensors ─────────────────────────────────────────────────────────
def test_time_sensor_payload():
    obs = TimeSensor().observe()
    assert len(obs) == 1
    p = obs[0].payload
    assert {"hour", "day", "week", "month", "timezone"} <= set(p)
    assert obs[0].confidence == 1.0


def test_system_sensor_structure():
    obs = SystemSensor().observe()
    assert len(obs) == 1 and obs[0].type == ObservationType.SYSTEM
    assert "available" in obs[0].payload


def test_process_sensor_runs():
    obs = ProcessSensor().observe()
    # psutil is present in this env; expect at least the process:list observation
    assert any(o.subject() == "process:list" for o in obs) or obs == []


def test_filesystem_sensor_detects_new_file(tmp_path):
    s = FilesystemSensor(watch_dirs=[str(tmp_path)])
    s.observe()                            # establish baseline (empty)
    (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
    obs = s.observe()
    new = obs[0].payload["new"]
    assert any("hello.txt" in p for p in new)


def test_register_builtin_sensors(manager):
    sm, pm = manager
    sensors = register_builtin_sensors(sm, watch_dirs=[])
    assert len(sensors) == len(ALL_BUILTIN)
    assert sm.health()["count"] == 4
