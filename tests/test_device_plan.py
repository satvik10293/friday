"""
tests/test_device_plan.py — M35 Device Wizard.

Measure-don't-guess is the contract: only measured backends can win, unmeasured
backends are recorded but never selected, and every failure path degrades to
cpu_only. The reader (core/intelligence/device.py) must always return a safe
torch device string.
"""

import json

import pytest

import core.intelligence.device as device
from core.launcher.device_plan import (
    DevicePlan, benchmark_device, build_device_plan, classify, detect_backends,
    read_device_plan, write_device_plan,
)


# ── classification ─────────────────────────────────────────────────────────────

def test_good_gpu_tier_splits_everything():
    plan = classify({"cpu": 100.0, "cuda": 30.0})
    assert plan.tier == "good_gpu"
    assert plan.backend == "cuda"
    assert plan.placements == {"local_models": "cuda", "embeddings": "cuda",
                               "stt": "cuda", "vision": "cuda"}
    assert plan.measured["speedup"] == pytest.approx(3.33, abs=0.01)


def test_average_gpu_tier_offloads_perception_only():
    plan = classify({"cpu": 100.0, "mps": 70.0})
    assert plan.tier == "average_gpu"
    assert plan.placements["local_models"] == "cpu", \
        "reasoning-path models must stay on CPU in the average tier"
    assert plan.placements["embeddings"] == "mps"
    assert plan.placements["stt"] == "mps"


def test_slow_gpu_is_classified_as_no_gpu():
    """An iGPU that benchmarks slower than the CPU is not a GPU worth using."""
    plan = classify({"cpu": 100.0, "cuda": 95.0})
    assert plan.tier == "cpu_only"
    assert all(d == "cpu" for d in plan.placements.values())


def test_unmeasured_backend_is_never_selected():
    """Detected-but-unmeasurable (e.g. OpenVINO GPU) must not win: unproven."""
    plan = classify({"cpu": 100.0, "openvino-gpu": None},
                    detected=[{"backend": "openvino-gpu", "measurable": False}])
    assert plan.tier == "cpu_only"
    assert plan.detected[0]["backend"] == "openvino-gpu"


def test_fastest_measured_backend_wins():
    plan = classify({"cpu": 100.0, "cuda": 20.0, "mps": 40.0})
    assert plan.backend == "cuda"


def test_no_measurements_at_all_degrades_to_cpu():
    plan = classify({"cpu": None})
    assert plan.tier == "cpu_only"
    assert plan.backend == "cpu"


# ── measurement + detection (real, this machine) ───────────────────────────────

def test_cpu_benchmark_returns_positive_ms():
    ms = benchmark_device("cpu", quick=True)
    assert ms is not None and ms > 0


def test_detect_backends_never_raises():
    backends = detect_backends()
    assert isinstance(backends, list)
    for b in backends:
        assert {"backend", "measurable"} <= set(b)


def test_build_device_plan_end_to_end_on_this_machine():
    plan = build_device_plan(quick=True)
    assert plan.tier in ("good_gpu", "average_gpu", "cpu_only")
    assert plan.measured.get("cpu") is not None
    assert set(plan.placements) == {"local_models", "embeddings", "stt", "vision"}


# ── persistence ────────────────────────────────────────────────────────────────

def test_write_merges_and_read_roundtrips(tmp_path):
    cfg = tmp_path / "friday_config.json"
    cfg.write_text(json.dumps({"owner_name": "Satvik", "wake_words": ["friday"]}))

    plan = classify({"cpu": 100.0, "cuda": 40.0})
    assert write_device_plan(plan, cfg)

    on_disk = json.loads(cfg.read_text())
    assert on_disk["owner_name"] == "Satvik", "merge clobbered existing config"
    assert on_disk["device_plan"]["tier"] == "good_gpu"
    assert read_device_plan(cfg) == on_disk["device_plan"]


def test_write_creates_config_when_missing(tmp_path):
    cfg = tmp_path / "friday_config.json"
    assert write_device_plan(classify({"cpu": None}), cfg)
    assert read_device_plan(cfg)["tier"] == "cpu_only"


def test_corrupt_config_is_not_overwritten(tmp_path):
    cfg = tmp_path / "friday_config.json"
    cfg.write_text("{not json")
    assert not write_device_plan(classify({"cpu": None}), cfg)
    assert cfg.read_text() == "{not json"


# ── the reader (core/intelligence/device.py) ───────────────────────────────────

def test_reader_returns_plan_placements(tmp_path):
    cfg = tmp_path / "friday_config.json"
    write_device_plan(classify({"cpu": 100.0, "cuda": 30.0}), cfg)
    assert device.preferred_device("embeddings", config_path=cfg) == "cuda"
    assert device.preferred_device("local_models", config_path=cfg) == "cuda"
    assert device.device_tier(config_path=cfg) == "good_gpu"


def test_reader_defaults_to_cpu_everywhere(tmp_path):
    missing = tmp_path / "nope.json"
    assert device.preferred_device("embeddings", config_path=missing) == "cpu"
    assert device.device_tier(config_path=missing) == "cpu_only"


def test_reader_degrades_non_torch_placements(tmp_path):
    cfg = tmp_path / "friday_config.json"
    plan = DevicePlan(tier="average_gpu", backend="openvino-gpu",
                      placements={"embeddings": "openvino-gpu"})
    write_device_plan(plan, cfg)
    assert device.preferred_device("embeddings", config_path=cfg) == "cpu", \
        "a placement with no torch runtime must degrade to cpu"


# ── wizard integration ─────────────────────────────────────────────────────────

class _FakePlatform:
    def __init__(self, root):
        self._root = root

    def config_dir(self):
        return self._root

    def data_dir(self):
        return self._root / "data"

    def ensure_dirs(self):
        (self._root / "data").mkdir(parents=True, exist_ok=True)


def test_wizard_writes_device_plan(tmp_path, monkeypatch):
    import core.launcher.device_plan as dp
    from core.launcher.first_run import FirstRunWizard

    monkeypatch.setattr(dp, "build_device_plan",
                        lambda quick=False: classify({"cpu": 100.0, "cuda": 25.0}))

    wizard = FirstRunWizard(root=tmp_path, platform=_FakePlatform(tmp_path))
    report = wizard.run(groq_key=None)

    assert report.device_plan_written
    assert report.device_plan["tier"] == "good_gpu"
    assert read_device_plan(tmp_path / "friday_config.json")["tier"] == "good_gpu"
    gpu_check = next(c for c in report.checks if c.name == "gpu")
    assert gpu_check.status in ("ok", "absent", "unknown")
