"""M12 — Intelligence cache (LRU) + optimizer (self-improvement, approval gate)."""

from core.intelligence.cache import IntelligenceCache, cache_key
from core.intelligence.optimizer import Optimizer


# ── cache ──────────────────────────────────────────────────────────────────────────
def test_cache_put_get():
    c = IntelligenceCache()
    c.put("k", 123)
    assert c.get("k") == 123
    assert c.stats()["hits"] == 1


def test_cache_miss():
    c = IntelligenceCache()
    assert c.get("absent") is None
    assert c.stats()["misses"] == 1


def test_lru_eviction():
    c = IntelligenceCache(capacity=2)
    c.put("a", 1); c.put("b", 2); c.put("c", 3)   # evicts "a"
    assert c.get("a") is None and c.get("b") == 2 and c.get("c") == 3
    assert len(c) == 2


def test_lru_recency():
    c = IntelligenceCache(capacity=2)
    c.put("a", 1); c.put("b", 2)
    c.get("a")                 # touch a → b is now least-recent
    c.put("c", 3)              # evicts b
    assert c.get("a") == 1 and c.get("b") is None


def test_get_or_compute():
    c = IntelligenceCache()
    calls = []
    fn = lambda: (calls.append(1), 99)[1]
    assert c.get_or_compute("k", fn) == 99
    assert c.get_or_compute("k", fn) == 99
    assert len(calls) == 1     # computed once


def test_resize_trims():
    c = IntelligenceCache(capacity=5)
    for i in range(5):
        c.put(str(i), i)
    c.resize(2)
    assert len(c) == 2


def test_hit_rate():
    c = IntelligenceCache()
    c.put("k", 1); c.get("k"); c.get("miss")
    assert 0 < c.stats()["hit_rate"] < 1


# ── optimizer ──────────────────────────────────────────────────────────────────────
def test_optimizer_no_bottleneck():
    recs = Optimizer(cache=IntelligenceCache()).analyze()
    assert any(r.area == "architecture" for r in recs)


def test_optimizer_flags_full_cache():
    c = IntelligenceCache(capacity=2)
    c.put("a", 1); c.put("b", 2)
    recs = Optimizer(cache=c).analyze()
    assert any(r.area == "caching" for r in recs)


def test_optimizer_auto_applies_safe():
    c = IntelligenceCache(capacity=2)
    c.put("a", 1); c.put("b", 2)
    applied = Optimizer(cache=c).apply_safe()
    assert c.capacity == 4 and applied


def test_self_improvement_gates_production():
    class FakeManager:
        def status(self): return {"unhealthy": [], "memory_mb": 8000}
        def restart_unhealthy(self): return []
    out = Optimizer(cache=IntelligenceCache(), model_manager=FakeManager()).self_improvement()
    assert "pending_approval" in out
    # the memory recommendation requires approval (never auto-applied to production)
    assert any(r["area"] == "memory" for r in out["pending_approval"])
    assert "require" in out["note"]
