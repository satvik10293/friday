"""M12 — Health monitor, model manager restart, and benchmark system."""

from core.intelligence.benchmark import BenchmarkSystem
from core.intelligence.builtin_models import MathModel, builtin_models
from core.intelligence.health_monitor import HealthMonitor
from core.intelligence.model_manager import ModelManager
from core.intelligence.registry import IntelligenceRegistry


# ── health monitor ─────────────────────────────────────────────────────────────────
def test_unhealthy_after_threshold():
    h = HealthMonitor(fail_threshold=3)
    for _ in range(3):
        h.record("m", success=False)
    assert not h.is_healthy("m")
    assert "m" in h.unhealthy_models()


def test_recovers_on_success():
    h = HealthMonitor(fail_threshold=2)
    h.record("m", success=False); h.record("m", success=False)
    assert not h.is_healthy("m")
    h.record("m", success=True)
    assert h.is_healthy("m")


def test_notify_callback():
    events = []
    h = HealthMonitor(fail_threshold=1, notify=lambda n, d: events.append((n, d["healthy"])))
    h.record("m", success=False)
    assert events and events[0][0] == "m"


def test_system_report():
    h = HealthMonitor()
    sysinfo = h.system()
    assert "available" in sysinfo


# ── model manager ──────────────────────────────────────────────────────────────────
def test_bootstrap_loads_team():
    reg = IntelligenceRegistry()
    mgr = ModelManager(reg)
    loaded = mgr.bootstrap(discover_optional=False)
    assert len(loaded) == 6
    assert mgr.memory_usage_mb() > 0


def test_restart_unhealthy():
    reg = IntelligenceRegistry()
    health = HealthMonitor(fail_threshold=1)
    mgr = ModelManager(reg, health=health)
    mgr.bootstrap(discover_optional=False)
    health.record("friday-math", success=False)      # mark unhealthy
    restarted = mgr.restart_unhealthy()
    assert "friday-math" in restarted
    assert health.is_healthy("friday-math")


def test_unload():
    reg = IntelligenceRegistry()
    mgr = ModelManager(reg)
    mgr.bootstrap(discover_optional=False)
    assert mgr.unload("friday-math")
    assert reg.get("friday-math") is None


# ── benchmark ──────────────────────────────────────────────────────────────────────
def test_benchmark_math():
    bs = BenchmarkSystem()
    result = bs.run(MathModel(), "math")
    assert result["score"] == 1.0 and result["passed"] == 2


def test_benchmark_run_all_and_rank():
    bs = BenchmarkSystem()
    models = builtin_models()
    for m in models:
        bs.run_all(m)
    ranking = bs.rank(models, "overall")
    assert ranking and ranking[0]["score"] >= ranking[-1]["score"]


def test_benchmark_persisted(tmp_path):
    from core.intelligence.store import IntelligenceStore
    store = IntelligenceStore(path=tmp_path / "i.db")
    BenchmarkSystem(store).run(MathModel(), "math")
    assert store.benchmarks("friday-math")
    store.close()
