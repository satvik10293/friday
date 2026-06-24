"""Tests for the version-controlled model registry reader (core.infra.model_registry)."""

import json

from core.infra.model_registry import ModelRegistry, get_model_registry


# ── against the real project registry ─────────────────────────────────────────────
def test_real_registry_loads():
    reg = get_model_registry()
    models = reg.list_models()
    assert models, "expected models/registry.json to list models"
    names = reg.names()
    assert "flan-t5" in names and "all-minilm-l6-v2" in names


def test_categories_present():
    reg = get_model_registry()
    cats = set(reg.categories())
    assert {"llm", "vision", "speech", "embeddings"} <= cats


def test_milestone_of():
    reg = get_model_registry()
    assert reg.milestone_of("all-minilm-l6-v2") == "M2"
    assert reg.milestone_of("flan-t5") == "3.0"


def test_metadata_merged_from_disk():
    reg = get_model_registry()
    flan = reg.get("flan-t5")
    # fields from metadata.json (not just registry.json) should be present
    assert flan.get("role")
    assert flan.get("used_by")


def test_weights_excluded_lists_nonweight_models():
    reg = get_model_registry()
    excluded = reg.weights_excluded()
    assert "flan-t5" in excluded               # weights not tracked
    assert "hand-landmarker" not in excluded   # the one tracked weight


def test_config_path_resolves():
    reg = get_model_registry()
    cfg = reg.config_path("flan-t5")
    assert cfg is not None and cfg.name == "config.yaml" and cfg.exists()


def test_health():
    reg = get_model_registry()
    h = reg.health()
    assert h["status"] == "ok"
    assert h["total"] >= 8
    assert h["weights_excluded"] >= 1


# ── against a synthetic registry (isolation) ──────────────────────────────────────
def test_custom_registry(tmp_path):
    (tmp_path / "llm" / "demo").mkdir(parents=True)
    (tmp_path / "registry.json").write_text(json.dumps({
        "models": [{"name": "demo", "category": "llm", "path": "llm/demo",
                    "milestone_introduced": "MX", "weights_tracked": False}]
    }), encoding="utf-8")
    (tmp_path / "llm" / "demo" / "metadata.json").write_text(
        json.dumps({"role": "demo model", "extra": 1}), encoding="utf-8")
    reg = ModelRegistry(models_dir=tmp_path)
    m = reg.get("demo")
    assert m["milestone_introduced"] == "MX"
    assert m["role"] == "demo model"          # merged from metadata.json
    assert reg.by_category("llm") and reg.by_category("vision") == []


def test_missing_registry_graceful(tmp_path):
    reg = ModelRegistry(models_dir=tmp_path / "nope")
    assert reg.list_models() == []
    assert reg.health()["status"] == "missing_registry"


def test_side_effect_free_import():
    import importlib
    importlib.import_module("core.infra.model_registry")
